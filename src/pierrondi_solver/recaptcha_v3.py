"""reCAPTCHA v3 token harvest via a local stealth browser ($0).

reCAPTCHA v3 is score-based: there is no interactive challenge to "solve".
The site calls ``grecaptcha.execute(sitekey, {action})`` and Google scores
the session server-side (0.0-1.0). What a local solver CAN do is execute the
same call in a clean stealth browser and return the resulting token. Whether
the destination site accepts it depends on the score, which depends on:

  1. Clean, stable browser fingerprint (stealth Chromium here).
  2. IP reputation (datacenter IPs score low; residential scores better).
  3. Human-like pacing on the page before execute() is called.
  4. Warm session cookies on the site's domain.

The previous guidance-only behavior is preserved as the failure path: when
the browser is unavailable or the harvest fails, the outcome reason tells
the caller how to improve posture, and the chain falls through to commercial
providers, which maintain high-score infrastructure.

Heavy deps (playwright) are optional/lazy.
"""
from __future__ import annotations

import time

from ..models import ChallengeType, SolveRequest, StrategyOutcome
from ..proxy import ProxyBackend, build_proxy_backend, playwright_proxy

V3_MITIGATION = (
    "v3_is_score_based: token harvested locally but acceptance depends on "
    "Google's server-side score; improve fingerprint/IP/pacing, or let the "
    "page fall back to a v2 challenge and resubmit as recaptcha_v2"
)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
_STEALTH_INIT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en', 'pt-BR']});
"""


def _missing_deps() -> list[str]:
    missing = []
    try:
        import playwright  # noqa: F401
    except ImportError:
        missing.append("playwright")
    return missing


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class RecaptchaV3Strategy:
    name = "v3_execute"
    provider = "pierrondi"

    def __init__(self, headless: bool = True, action: str = "submit", proxy_backend: ProxyBackend | None = None) -> None:
        self.headless = headless
        self.action = action
        self.proxy_backend = proxy_backend or build_proxy_backend()

    def supports(self, challenge_type: ChallengeType) -> bool:
        return challenge_type == ChallengeType.recaptcha_v3

    def solve(self, request: SolveRequest) -> StrategyOutcome:
        started = time.monotonic()

        missing = _missing_deps()
        if missing:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason=f"deps_missing: {'; '.join(missing)}",
            )

        proxy_config, proxy_error = self._resolve_proxy(request, started)
        if proxy_error:
            return proxy_error
        proxy_cs = proxy_config.connect_string if proxy_config else ""

        try:
            token = self._harvest_token(
                request.page_url, request.sitekey, request.timeout_s, proxy_cs
            )
        except Exception as exc:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason=f"v3_harvest_failed: {type(exc).__name__}: {exc}"[:400],
            )
        if not token:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason="v3_no_token_within_timeout",
            )
        extra = {
            "engine": "chromium",
            "score_note": V3_MITIGATION,
            "usage": "single-use g-recaptcha-response; submit once, immediately",
        }
        if proxy_config:
            extra["proxy"] = {
                "kind": proxy_config.kind,
                "fingerprint": proxy_config.fingerprint,
            }
        return StrategyOutcome(
            token=token,
            strategy=self.name,
            provider=self.provider,
            latency_ms=_elapsed_ms(started),
            cost_usd=0.0,
            extra=extra,
        )

    def _resolve_proxy(
        self, request: SolveRequest, started: float
    ) -> tuple:
        import os

        proxy_required = bool(
            os.environ.get("SOLVER_PROXY") or os.environ.get("SOLVER_PROXY_ENDPOINT")
        )
        proxy_config = self.proxy_backend.resolve(request.lane)
        if proxy_required and proxy_config is None:
            return None, StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason="deps_missing: proxy_unavailable",
            )
        return proxy_config, None

    def _harvest_token(self, page_url: str, sitekey: str, timeout_s: int, proxy: str = "") -> str:
        """Execute grecaptcha in a stealth Chromium and return the token."""
        from playwright.sync_api import sync_playwright

        timeout_ms = timeout_s * 1000
        with sync_playwright() as p:
            launch_kwargs = {"headless": self.headless}
            launch_kwargs.update({"proxy": playwright_proxy(proxy)} if proxy else {})
            browser = p.chromium.launch(**launch_kwargs)
            try:
                ctx = browser.new_context(
                    user_agent=_USER_AGENT,
                    viewport={"width": 1440, "height": 900},
                    locale="en-US",
                )
                ctx.add_init_script(_STEALTH_INIT)
                page = ctx.new_page()
                page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_function(
                    """() => typeof grecaptcha !== 'undefined'
                        && typeof grecaptcha.ready === 'function'
                        && typeof grecaptcha.execute === 'function'""",
                    timeout=timeout_ms,
                )
                # brief human-like pacing before execute (score posture)
                page.mouse.move(400, 300)
                page.wait_for_timeout(1500)
                page.mouse.move(420, 320)
                return page.evaluate(
                    """([sitekey, action]) => new Promise((resolve, reject) => {
                        grecaptcha.ready(() => {
                            grecaptcha.execute(sitekey, {action: action})
                                .then(resolve)
                                .catch(reject);
                        });
                    })""",
                    [sitekey, self.action],
                ) or ""
            finally:
                browser.close()
