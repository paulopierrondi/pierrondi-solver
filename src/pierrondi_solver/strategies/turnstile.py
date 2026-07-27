"""Turnstile token harvest via a local stealth browser ($0).

Turnstile is a managed widget: once the page's JavaScript runs in a clean
browser it usually completes non-interactively (and always does with
Cloudflare's official testing sitekeys). The harvest = load the page, wait
for the widget to populate the hidden ``cf-turnstile-response`` field, and
read the token.

Real-site success depends on IP/fingerprint reputation — the same honest
caveat as every local strategy. When the widget refuses to complete, the
chain falls through to commercial providers.

Heavy deps (playwright) are optional/lazy: when missing, the strategy
reports ``deps_missing`` and the chain skips it without burning breaker
budget.
"""
from __future__ import annotations

import time

from ..models import ChallengeType, SolveRequest, StrategyOutcome

TOKEN_SELECTOR = (
    "input[name='cf-turnstile-response'], textarea[name='cf-turnstile-response']"
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


class TurnstileStrategy:
    name = "turnstile_harvest"
    provider = "pierrondi"

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless

    def supports(self, challenge_type: ChallengeType) -> bool:
        return challenge_type == ChallengeType.turnstile

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

        try:
            token = self._harvest_token(request.page_url, request.timeout_s)
        except Exception as exc:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason=f"turnstile_failed: {type(exc).__name__}: {exc}"[:400],
            )
        if not token:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason="turnstile_no_token_within_timeout",
            )
        return StrategyOutcome(
            token=token,
            strategy=self.name,
            provider=self.provider,
            latency_ms=_elapsed_ms(started),
            cost_usd=0.0,
            extra={
                "engine": "chromium",
                "usage": "single-use cf-turnstile-response; submit once, immediately",
            },
        )

    def _harvest_token(self, page_url: str, timeout_s: int) -> str:
        """Drive a stealth Chromium to the page and read the widget token."""
        from playwright.sync_api import sync_playwright

        timeout_ms = timeout_s * 1000
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
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
                    """() => {
                        const el = document.querySelector(
                            "input[name='cf-turnstile-response'], textarea[name='cf-turnstile-response']");
                        return el && el.value && el.value.length > 0;
                    }""",
                    timeout=timeout_ms,
                )
                return page.eval_on_selector(TOKEN_SELECTOR, "el => el.value") or ""
            finally:
                browser.close()
