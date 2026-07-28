"""Firefox backend (Playwright).

Same clearance-harvest algorithm as Chromium, but on the Firefox engine. The
fingerprint surface differs from Chrome, so no Chrome-oriented stealth init
script is injected (``window.chrome`` / ``navigator.webdriver`` Chrome-isms do
not apply). Diversifying the engine is useful against managed challenges that
fingerprint Chromium specifically.
"""
from __future__ import annotations

import time

from .base import BrowserOpts, HarvestedContext

CLEARANCE_COOKIE = "cf_clearance"


def _playwright_missing() -> bool:
    try:
        import playwright  # noqa: F401

        return False
    except ImportError:
        return True


def _firefox_browser_missing() -> bool:
    """Playwright's chromium bundle is the common install; the firefox bundle
    is a separate ``playwright install firefox`` step. Detect a missing firefox
    executable without a network call."""
    if _playwright_missing():
        return True
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            pw.firefox.executable_path  # raises if the browser is not installed
        return False
    except Exception:
        return True


class FirefoxBackend:
    """Playwright Firefox clearance harvester (headful by default)."""

    name = "firefox"
    supports_proxy = True

    def deps_missing(self) -> list[str]:
        missing: list[str] = []
        if _playwright_missing():
            missing.append("pip install '.[local-solve]'")
        if _firefox_browser_missing():
            missing.append("playwright install firefox")
        return missing

    def harvest_clearance(
        self, page_url: str, timeout_s: int, opts: BrowserOpts
    ) -> HarvestedContext:
        from playwright.sync_api import sync_playwright

        deadline = time.monotonic() + timeout_s
        with sync_playwright() as pw:
            browser = pw.firefox.launch(headless=opts.headless)
            context_kwargs: dict = {
                "user_agent": opts.user_agent,
                "viewport": opts.viewport,
                "locale": opts.locale,
            }
            if opts.proxy:
                context_kwargs["proxy"] = {"server": opts.proxy}
            context = browser.new_context(**context_kwargs)
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
