"""Solver chain: tries providers in order, honoring the circuit breaker,
logging every attempt to telemetry, returning the first solved outcome.

The caller-facing ``request.timeout_s`` is the budget for the WHOLE chain:
each provider attempt receives only the remaining seconds, and an exhausted
budget stops the chain with a ``chain_deadline_exceeded`` marker.
"""
from __future__ import annotations

import time

from .circuit_breaker import CircuitBreaker
from .config import PROVIDER_PIERRONDI, Config
from .models import (
    ChallengeType,
    SolvePurpose,
    SolveRequest,
    SolveResult,
    StrategyOutcome,
    UnsolvedError,
)
from .providers.commercial import build_commercial_providers
from .proxy import build_proxy_backend
from .strategies.cloudflare_clearance import build_cloudflare_strategy
from .strategies.hcaptcha import HCaptchaAudioStrategy
from .strategies.recaptcha_v2 import RecaptchaV2Strategy
from .strategies.recaptcha_v2_image import register_classifier
from .strategies.recaptcha_v3 import RecaptchaV3Strategy
from .strategies.turnstile import TurnstileStrategy
from .strategies.vision_ollama import build_default_classifier
from .telemetry import AttemptLog, Telemetry

NO_API_KEY = "no_api_key"

# Floor for the per-attempt timeout once the chain budget is nearly spent, so
# the last attempt gets a minimal chance instead of a zero-second starvation.
MIN_ATTEMPT_TIMEOUT_S = 5

# Reason substrings marking a transport-level failure worth one local retry.
_TRANSIENT_REASON_MARKERS = (
    "TimeoutError",
    "ERR_CONNECTION",
    "ERR_INTERNET",
    "Connection",
)


class SolverChain:
    def __init__(
        self,
        config: Config,
        breaker: CircuitBreaker,
        telemetry: Telemetry,
        strategies: dict | None = None,
    ) -> None:
        self.config = config
        self.breaker = breaker
        self.telemetry = telemetry
        if strategies is None:
            commercial = build_commercial_providers(config.api_keys, config.proxies)
            proxy_backend = build_proxy_backend(
                {
                    "SOLVER_PROXY": config.proxy,
                    "SOLVER_PROXY_ENDPOINT": config.proxy_endpoint,
                    "SOLVER_PROXY_STICKY": "1" if config.proxy_sticky else "",
                    "SOLVER_PROXY_STICKY_TTL": str(config.proxy_sticky_ttl),
                }
            )
            classifier = build_default_classifier()
            if classifier is not None:
                register_classifier(classifier)
            strategies = {
                PROVIDER_PIERRONDI: [
                    RecaptchaV2Strategy(),
                    RecaptchaV3Strategy(),
                    TurnstileStrategy(),
                    HCaptchaAudioStrategy(
                        accessibility_cookie=config.hcaptcha_accessibility_cookie
                    ),
                    build_cloudflare_strategy(
                        config.browser_engine,
                        proxy_backend=proxy_backend,
                        proxy_required=bool(config.proxy or config.proxy_endpoint),
                    ),
                ],
                "capsolver": [commercial["capsolver"]],
                "capmonster": [commercial["capmonster"]],
                "2captcha": [commercial["2captcha"]],
            }
        self.strategies = strategies

    def solve(self, request: SolveRequest) -> tuple[SolveResult | None, UnsolvedError | None]:
        attempts: list[str] = []
        deadline = time.monotonic() + request.timeout_s
        for provider in self.config.chain():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                attempts.append("chain_deadline_exceeded")
                break
            if not self.breaker.is_available(provider):
                attempts.append(f"{provider}: circuit_open")
                continue
            attempt_request = request.model_copy(
                update={"timeout_s": max(MIN_ATTEMPT_TIMEOUT_S, int(remaining))}
            )
            outcome = self._try_provider(provider, attempt_request)
            if outcome is None:
                continue
            attempts.append(f"{provider}/{outcome.strategy}: {outcome.reason or 'ok'}")
            if outcome.reason.startswith((NO_API_KEY, "deps_missing", "not_implemented")):
                continue  # provider cannot run here: skip without burning breaker budget
            self._record(provider, request, outcome)
            retry = self._transient_retry(provider, request, outcome, deadline)
            if retry is not None:
                attempts.append(
                    f"{provider}/{retry.strategy}: {retry.reason or 'ok'} (transient_retry)"
                )
                self._record(provider, request, retry)
                outcome = retry
            if outcome.solved:
                extra = dict(outcome.extra)
                extra["artifact_policy"] = request.artifact_policy()
                return (
                    SolveResult(
                        token=outcome.token,
                        strategy=outcome.strategy,
                        provider=provider,
                        latency_ms=outcome.latency_ms,
                        cost_usd=outcome.cost_usd,
                        extra=extra,
                    ),
                    None,
                )
        reason = "; ".join(attempts) or "no providers configured"
        return None, UnsolvedError(reason=reason, attempts=attempts)

    def _transient_retry(
        self,
        provider: str,
        request: SolveRequest,
        outcome: StrategyOutcome,
        deadline: float,
    ) -> StrategyOutcome | None:
        """One retry of the local strategy on transient transport failures.

        Commercial providers bill per call and a non-transient reason will not
        change on an immediate retry, so both are excluded. ``state_change``
        requests are never implicitly retried (stage-aware contract).
        """
        if (
            outcome.solved
            or provider != PROVIDER_PIERRONDI
            or request.purpose == SolvePurpose.state_change
            or not _is_transient(outcome.reason)
        ):
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        retry = self._try_provider(
            provider,
            request.model_copy(
                update={"timeout_s": max(MIN_ATTEMPT_TIMEOUT_S, int(remaining))}
            ),
        )
        if retry is None or retry.reason.startswith(
            (NO_API_KEY, "deps_missing", "not_implemented")
        ):
            return None
        return retry

    def _try_provider(self, provider: str, request: SolveRequest) -> StrategyOutcome | None:
        for strategy in self.strategies.get(provider, []):
            if not strategy.supports(request.type):
                continue
            outcome = strategy.solve(request)
            # no_api_key / deps_missing / not_implemented mean "this provider
            # cannot run here" -> do not burn breaker budget, try next provider.
            if outcome.reason.startswith((NO_API_KEY, "deps_missing", "not_implemented")):
                return StrategyOutcome(
                    strategy=outcome.strategy,
                    provider=provider,
                    reason=outcome.reason,
                )
            return outcome
        return None

    def _record(self, provider: str, request: SolveRequest, outcome: StrategyOutcome) -> None:
        self.breaker.record(provider, outcome.solved)
        self.telemetry.log_attempt(
            AttemptLog(
                provider=provider,
                challenge_type=request.type.value,
                strategy=outcome.strategy,
                page_url=request.page_url,
                lane=request.lane,
                latency_ms=outcome.latency_ms,
                cost_usd=outcome.cost_usd,
                success=outcome.solved,
                token=outcome.token or "",
                reason=outcome.reason,
                purpose=request.purpose.value,
                operation_id=request.operation_id,
            )
        )


def _is_transient(reason: str) -> bool:
    """True when the failure reason looks like a transient transport error."""
    return any(marker in reason for marker in _TRANSIENT_REASON_MARKERS)


def _seed_breaker(breaker: CircuitBreaker, telemetry: Telemetry, config: Config) -> None:
    """Pre-load failures for providers already degraded in recent telemetry.

    A provider that was failing before a restart should not burn caller
    latency re-learning that. Degrade-safe: any telemetry read error starts
    the breaker clean.
    """
    try:
        outcomes = telemetry.provider_outcomes(window_s=config.breaker_window_s)
    except Exception:
        return
    for provider, results in outcomes.items():
        if len(results) < config.breaker_min_samples:
            continue
        failures = sum(1 for ok in results if not ok)
        if failures / len(results) > config.breaker_failure_rate:
            for _ in range(config.breaker_min_samples):
                breaker.record(provider, success=False)


def build_default_chain(config: Config) -> SolverChain:
    breaker = CircuitBreaker(
        failure_rate=config.breaker_failure_rate,
        min_samples=config.breaker_min_samples,
        window_s=config.breaker_window_s,
        cooldown_s=config.breaker_cooldown_s,
    )
    telemetry = Telemetry(config.telemetry_db)
    _seed_breaker(breaker, telemetry, config)
    return SolverChain(config=config, breaker=breaker, telemetry=telemetry)
