"""Cloudflare interstitial / IUAM ("Just a moment...", JS challenge).

This is NOT a token-in-field challenge: the browser must pass Cloudflare's
JS/behavioral check, after which Cloudflare sets a ``cf_clearance`` cookie.
The solve = (cf_clearance cookie value, the exact User-Agent used) — the
caller MUST reuse both together for subsequent requests (the clearance is
bound to UA + IP).

Local strategy: real Chromium via Playwright with automation flags off,
navigate, wait for the cf_clearance cookie (up to timeout), harvest it.

Heavy dep (playwright) is optional/lazy: missing -> ``deps_missing`` so the
chain falls through to commercial providers (CapSolver AntiCloudflareTask,
which requires a proxy).
"""
from __future__ import annotations

import time

from ..models import ChallengeType, SolveRequest, StrategyOutcome

CLEARANCE_COOKIE = "cf_clearance"

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
]

_STEALTH_INIT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en', 'pt-BR']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || {runtime: {}};
"""


def _playwright_missing() -> bool:
    try:
        import playwright  # noqa: F401
        return False
    except ImportError:
        return True


class CloudflareClearanceStrategy:
    name = "cf_clearance"
    provider = "pierrondi"

    def __init__(self, headless: bool = False) -> None:
        # headful is materially more reliable against managed challenges
        self.headless = headless

    def supports(self, challenge_type: ChallengeType) -> bool:
        return challenge_type == ChallengeType.cloudflare

    def solve(self, request: SolveRequest) -> StrategyOutcome:
        started = time.monotonic()
        if _playwright_missing():
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason="deps_missing: pip install '.[local-solve]' + playwright install chromium",
            )
        try:
            clearance, user_agent = self._harvest_clearance(request)
        except Exception as exc:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason=f"cf_clearance_failed: {type(exc).__name__}: {exc}"[:400],
            )
        if not clearance:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason="cf_clearance_not_granted_within_timeout",
            )
        return StrategyOutcome(
            token=clearance,
            strategy=self.name,
            provider=self.provider,
            latency_ms=_elapsed_ms(started),
            cost_usd=0.0,
            extra={
                "user_agent": user_agent,
                "cookies": {CLEARANCE_COOKIE: clearance},
                "usage": "send Cookie cf_clearance with the SAME user_agent from the SAME IP",
            },
        )

    def _harvest_clearance(self, request: SolveRequest) -> tuple[str, str]:
        from playwright.sync_api import sync_playwright

        deadline = time.monotonic() + request.timeout_s
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless, args=_LAUNCH_ARGS)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
                locale="en-US",
            )
            context.add_init_script(_STEALTH_INIT)
            page = context.new_page()
            try:
                page.goto(request.page_url, wait_until="domcontentloaded",
                          timeout=min(60_000, request.timeout_s * 1000))
                while time.monotonic() < deadline:
                    cookies = {c["name"]: c["value"] for c in context.cookies()}
                    if cookies.get(CLEARANCE_COOKIE):
                        return cookies[CLEARANCE_COOKIE], page.evaluate("navigator.userAgent")
                    page.wait_for_timeout(2000)
                return "", ""
            finally:
                browser.close()


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
