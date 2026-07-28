"""Chromium backend (Playwright).

Behavior moved verbatim from the original ``cloudflare_clearance._harvest_clearance``:
stealth launch args, init script, fixed UA/viewport/locale, poll for cf_clearance.
"""
from __future__ import annotations

import time

from .base import BrowserOpts, HarvestedContext

CLEARANCE_COOKIE = "cf_clearance"

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
]

# Chrome-oriented stealth: hides the webdriver flag and fakes a couple of
# surfaces Cloudflare inspects on Chromium. Not applicable to Firefox.
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


class ChromiumBackend:
    """Playwright Chromium clearance harvester (headful by default)."""

    name = "chromium"
    supports_proxy = True

    def deps_missing(self) -> list[str]:
        if _playwright_missing():
            return ["pip install '.[local-solve]' + playwright install chromium"]
        return []

    def harvest_clearance(
        self, page_url: str, timeout_s: int, opts: BrowserOpts
    ) -> HarvestedContext:
        from playwright.sync_api import sync_playwright

        deadline = time.monotonic() + timeout_s
        with sync_playwright() as pw:
            launch_kwargs: dict = {"headless": opts.headless, "args": _LAUNCH_ARGS}
            context_kwargs: dict = {
                "user_agent": opts.user_agent,
                "viewport": opts.viewport,
                "locale": opts.locale,
            }
            if opts.proxy:
                context_kwargs["proxy"] = {"server": opts.proxy}
            browser = pw.chromium.launch(**launch_kwargs)
            context = browser.new_context(**context_kwargs)
            context.add_init_script(_STEALTH_INIT)
            page = context.new_page()
            try:
                page.goto(
                    page_url,
                    wait_until="domcontentloaded",
                    timeout=min(60_000, timeout_s * 1000),
                )
                while time.monotonic() < deadline:
                    cookies = {c["name"]: c["value"] for c in context.cookies()}
                    if cookies.get(CLEARANCE_COOKIE):
                        return HarvestedContext(
                            clearance=cookies[CLEARANCE_COOKIE],
                            user_agent=page.evaluate("navigator.userAgent"),
                            cookies=cookies,
                            engine=self.name,
                        )
                    page.wait_for_timeout(2000)
                return HarvestedContext(
                    clearance="",
                    user_agent=opts.user_agent,
                    cookies={},
                    engine=self.name,
                )
            finally:
                browser.close()
