"""Solver chain: tries providers in order, honoring the circuit breaker,
logging every attempt to telemetry, returning the first solved outcome.
"""
from __future__ import annotations

from .circuit_breaker import CircuitBreaker
from .config import PROVIDER_PIERRONDI, Config
from .models import ChallengeType, SolveRequest, SolveResult, StrategyOutcome, UnsolvedError
from .providers.commercial import build_commercial_providers
from .proxy import build_proxy_backend
from .strategies.cloudflare_clearance import build_cloudflare_strategy
from .strategies.hcaptcha import HCaptchaAudioStrategy
from .strategies.recaptcha_v2_audio import RecaptchaV2AudioStrategy
from .strategies.recaptcha_v2_image import RecaptchaV2ImageStrategy
from .strategies.recaptcha_v3 import RecaptchaV3Strategy
from .telemetry import Telemetry

NO_API_KEY = "no_api_key"


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
            strategies = {
                PROVIDER_PIERRONDI: [
                    RecaptchaV2AudioStrategy(),
                    RecaptchaV2ImageStrategy(),
                    RecaptchaV3Strategy(),
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
        for provider in self.config.chain():
            if not self.breaker.is_available(provider):
                attempts.append(f"{provider}: circuit_open")
                continue
            outcome = self._try_provider(provider, request)
            if outcome is None:
                continue
            attempts.append(f"{provider}/{outcome.strategy}: {outcome.reason or 'ok'}")
            if outcome.reason.startswith((NO_API_KEY, "deps_missing", "not_implemented")):
                continue  # provider cannot run here: skip without burning breaker budget
            self._record(provider, request, outcome)
            if outcome.solved:
                return (
                    SolveResult(
                        token=outcome.token,
                        strategy=outcome.strategy,
                        provider=provider,
                        latency_ms=outcome.latency_ms,
                        cost_usd=outcome.cost_usd,
                        extra=outcome.extra,
                    ),
                    None,
                )
        reason = "; ".join(attempts) or "no providers configured"
        return None, UnsolvedError(reason=reason, attempts=attempts)

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
        )


def build_default_chain(config: Config) -> SolverChain:
    breaker = CircuitBreaker(
        failure_rate=config.breaker_failure_rate,
        min_samples=config.breaker_min_samples,
        window_s=config.breaker_window_s,
    )
    return SolverChain(config=config, breaker=breaker, telemetry=Telemetry(config.telemetry_db))
