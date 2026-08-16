"""Cloudflare interstitial / IUAM ("Just a moment...", JS challenge).

This is NOT a token-in-field challenge: the browser must pass Cloudflare's
JS/behavioral check, after which Cloudflare sets a ``cf_clearance`` cookie.
The solve = (cf_clearance cookie value, the exact User-Agent used) — the
caller MUST reuse both together for subsequent requests (the clearance is
bound to UA + IP).

The browser engine is pluggable via ``BrowserBackend`` (see ``browser/``).
The default backend is Chromium (backward compatible). Other engines
(Firefox, and later camoufox/nodriver/patchright) can be injected or
selected via ``SOLVER_BROWSER_ENGINE``.

Heavy deps (playwright) are optional/lazy: a backend reports ``deps_missing``
and the chain falls through to commercial providers (CapSolver
AntiCloudflareTask, which requires a proxy).
"""
from __future__ import annotations

import time

from ..browser import ChromiumBackend, get_browser
from ..browser.base import BrowserBackend, BrowserOpts
from ..models import ChallengeType, SolveRequest, StrategyOutcome
from ..proxy import ProxyBackend, ProxyConfig, StaticProxyBackend

CLEARANCE_COOKIE = "cf_clearance"


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class CloudflareClearanceStrategy:
    name = "cf_clearance"
    provider = "pierrondi"

    def __init__(
        self,
        headless: bool = True,
        backend: BrowserBackend | None = None,
        proxy_backend: ProxyBackend | None = None,
        proxy_required: bool = False,
    ) -> None:
        # unattended runs stay silent by default; headful remains an explicit
        # diagnostic opt-in (headless=False)
        self.headless = headless
        # default backend keeps current behavior (Chromium) when not injected
        self.backend: BrowserBackend = backend or ChromiumBackend()
        self.proxy_backend = proxy_backend or StaticProxyBackend()
        self.proxy_required = proxy_required

    def supports(self, challenge_type: ChallengeType) -> bool:
        return challenge_type == ChallengeType.cloudflare

    def solve(self, request: SolveRequest) -> StrategyOutcome:
        started = time.monotonic()

        missing = self.backend.deps_missing()
        if missing:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason=f"deps_missing: {self.backend.name}: {'; '.join(missing)}",
            )

        proxy_config, proxy_error = self._resolve_proxy(request, started)
        if proxy_error:
            return proxy_error

        opts = BrowserOpts(
            headless=self.headless,
            proxy=proxy_config.connect_string if proxy_config else "",
        )
        try:
            ctx = self.backend.harvest_clearance(
                request.page_url, request.timeout_s, opts
            )
        except Exception as exc:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason=f"cf_clearance_failed: {type(exc).__name__}: {exc}"[:400],
            )
        if not ctx.clearance:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason="cf_clearance_not_granted_within_timeout",
            )
        extra = {
            "user_agent": ctx.user_agent,
            "cookies": {CLEARANCE_COOKIE: ctx.clearance},
            "engine": ctx.engine,
            "usage": "send Cookie cf_clearance with the SAME user_agent from the SAME IP",
        }
        if proxy_config:
            extra["proxy"] = {
                "kind": proxy_config.kind,
                "fingerprint": proxy_config.fingerprint,
            }
        return StrategyOutcome(
            token=ctx.clearance,
            strategy=self.name,
            provider=self.provider,
            latency_ms=_elapsed_ms(started),
            cost_usd=0.0,
            extra=extra,
        )

    def _resolve_proxy(
        self, request: SolveRequest, started: float
    ) -> tuple[ProxyConfig | None, StrategyOutcome | None]:
        proxy_config = self.proxy_backend.resolve(request.lane)
        reason = ""
        if self.proxy_required and proxy_config is None:
            reason = "deps_missing: proxy_unavailable"
        elif proxy_config and not getattr(self.backend, "supports_proxy", False):
            reason = f"deps_missing: {self.backend.name}: proxy_not_supported"
        if not reason:
            return proxy_config, None
        return None, StrategyOutcome(
            strategy=self.name,
            provider=self.provider,
            latency_ms=_elapsed_ms(started),
            reason=reason,
        )


def build_cloudflare_strategy(
    engine: str = "chromium",
    proxy_backend: ProxyBackend | None = None,
    proxy_required: bool = False,
) -> CloudflareClearanceStrategy:
    """Build the Cloudflare strategy with the backend selected by engine name.

    Unknown engine names fall back to a backend whose ``deps_missing`` reports
    ``unknown_engine``, so the chain skips it gracefully rather than crashing.
    ``proxy`` optionally routes the harvest through a controlled IP.
    """
    try:
        backend = get_browser(engine)
    except ValueError:
        # Defer the unknown-engine signal to deps_missing via a tiny shim that
        # always reports the hint; keeps construction total.
        from ..browser.base import BrowserOpts, HarvestedContext

        class _UnknownBackend:
            name = "unknown"

            def deps_missing(self) -> list[str]:
                return [f"unknown_engine: {engine}"]

            def harvest_clearance(self, page_url, timeout_s, opts):  # pragma: no cover
                raise RuntimeError(f"unknown_engine: {engine}")

        backend = _UnknownBackend()  # type: ignore[assignment]
    return CloudflareClearanceStrategy(
        backend=backend,
        proxy_backend=proxy_backend,
        proxy_required=proxy_required,
    )
