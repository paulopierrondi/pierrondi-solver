"""Per-provider circuit breaker: opens when recent failure rate exceeds threshold."""
from __future__ import annotations

import time
from collections import deque


class CircuitBreaker:
    """Tracks (timestamp, success) samples per provider in a sliding window.

    A provider is *open* (unavailable) when it has at least ``min_samples``
    samples in the window and the failure rate exceeds ``failure_rate``.
    After ``cooldown_s`` in the open state, exactly one half-open trial
    attempt is allowed: success closes the breaker (fresh window), failure
    re-opens it and restarts the cooldown.
    """

    def __init__(
        self,
        failure_rate: float = 0.30,
        min_samples: int = 5,
        window_s: int = 3600,
        cooldown_s: int = 300,
        clock=time.monotonic,
    ) -> None:
        if not 0.0 < failure_rate <= 1.0:
            raise ValueError("failure_rate must be in (0, 1]")
        if min_samples < 1:
            raise ValueError("min_samples must be >= 1")
        if cooldown_s < 0:
            raise ValueError("cooldown_s must be >= 0")
        self.failure_rate = failure_rate
        self.min_samples = min_samples
        self.window_s = window_s
        self.cooldown_s = cooldown_s
        self._clock = clock
        self._samples: dict[str, deque] = {}
        self._opened_at: dict[str, float] = {}
        self._probe_in_flight: set[str] = set()

    def _prune(self, provider: str) -> deque:
        samples = self._samples.setdefault(provider, deque())
        cutoff = self._clock() - self.window_s
        while samples and samples[0][0] < cutoff:
            samples.popleft()
        return samples

    def _closed(self, samples: deque) -> bool:
        if len(samples) < self.min_samples:
            return True
        failures = sum(1 for _, ok in samples if not ok)
        return (failures / len(samples)) <= self.failure_rate

    def record(self, provider: str, success: bool) -> None:
        self._prune(provider).append((self._clock(), bool(success)))
        if provider not in self._probe_in_flight:
            return
        self._probe_in_flight.discard(provider)
        if success:
            # Half-open trial passed: close the breaker with a fresh window.
            self._samples.pop(provider, None)
            self._opened_at.pop(provider, None)
        else:
            # Trial failed: re-open and restart the cooldown.
            self._opened_at[provider] = self._clock()

    def is_available(self, provider: str) -> bool:
        samples = self._prune(provider)
        if self._closed(samples):
            self._opened_at.pop(provider, None)
            self._probe_in_flight.discard(provider)
            return True
        opened_at = self._opened_at.setdefault(provider, self._clock())
        if (
            self._clock() - opened_at >= self.cooldown_s
            and provider not in self._probe_in_flight
        ):
            self._probe_in_flight.add(provider)  # exactly one trial attempt
            return True
        return False

    def stats(self, provider: str) -> dict:
        samples = self._prune(provider)
        failures = sum(1 for _, ok in samples if not ok)
        total = len(samples)
        # Side-effect free: reading stats must not arm a half-open probe.
        available = self._closed(samples) or provider in self._probe_in_flight
        return {
            "provider": provider,
            "samples": total,
            "failures": failures,
            "failure_rate": (failures / total) if total else 0.0,
            "available": available,
            "half_open": provider in self._probe_in_flight,
        }
