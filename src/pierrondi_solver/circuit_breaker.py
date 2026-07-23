"""Per-provider circuit breaker: opens when recent failure rate exceeds threshold."""
from __future__ import annotations

import time
from collections import deque


class CircuitBreaker:
    """Tracks (timestamp, success) samples per provider in a sliding window.

    A provider is *open* (unavailable) when it has at least ``min_samples``
    samples in the window and the failure rate exceeds ``failure_rate``.
    """

    def __init__(
        self,
        failure_rate: float = 0.30,
        min_samples: int = 5,
        window_s: int = 3600,
        clock=time.monotonic,
    ) -> None:
        if not 0.0 < failure_rate <= 1.0:
            raise ValueError("failure_rate must be in (0, 1]")
        if min_samples < 1:
            raise ValueError("min_samples must be >= 1")
        self.failure_rate = failure_rate
        self.min_samples = min_samples
        self.window_s = window_s
        self._clock = clock
        self._samples: dict[str, deque] = {}

    def _prune(self, provider: str) -> deque:
        samples = self._samples.setdefault(provider, deque())
        cutoff = self._clock() - self.window_s
        while samples and samples[0][0] < cutoff:
            samples.popleft()
        return samples

    def record(self, provider: str, success: bool) -> None:
        self._prune(provider).append((self._clock(), bool(success)))

    def is_available(self, provider: str) -> bool:
        samples = self._prune(provider)
        if len(samples) < self.min_samples:
            return True
        failures = sum(1 for _, ok in samples if not ok)
        return (failures / len(samples)) <= self.failure_rate

    def stats(self, provider: str) -> dict:
        samples = self._prune(provider)
        failures = sum(1 for _, ok in samples if not ok)
        total = len(samples)
        return {
            "provider": provider,
            "samples": total,
            "failures": failures,
            "failure_rate": (failures / total) if total else 0.0,
            "available": self.is_available(provider),
        }
