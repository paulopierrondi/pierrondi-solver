"""nodriver backend — Chrome via CDP without webdriver.

``nodriver`` (successor of undetected-chromedriver) drives a real Chrome binary
through the Chrome DevTools Protocol directly. It never starts a webdriver
process, so it does not expose ``navigator.webdriver = true`` or the other
automation signals that Playwright/Selenium leak. This is materially harder for
managed challenges (Cloudflare, Datadome, Kasada) to fingerprint.

Trade-offs vs the Playwright Chromium backend:
- Pro: starts undetected; no webdriver artifacts.
- Con: CDP-only API, async, smaller surface than Playwright.
- Dep: optional (``pip install '.[nodriver]'``); missing -> ``deps_missing``.

The ``BrowserBackend.harvest_clearance`` interface is synchronous, but nodriver
is async-first. We bridge by running the coroutine on a dedicated event loop
inside the call (nodriver owns its loop; we do not reuse a foreign one).
"""
from __future__ import annotations

import asyncio

from .base import BrowserOpts, HarvestedContext

CLEARANCE_COOKIE = "cf_clearance"


def _nodriver_missing() -> bool:
    try:
        import nodriver  # noqa: F401

        return False
    except ImportError:
        return True


class NodriverBackend:
    """Chrome-via-CDP (undetected) clearance harvester."""

    name = "nodriver"
    # Authenticated proxy support needs a dedicated nodriver browser context;
    # fail closed in the strategy instead of silently harvesting on the host IP.
    supports_proxy = False

    def deps_missing(self) -> list[str]:
        if _nodriver_missing():
            return ["pip install '.[nodriver]'"]
        return []

    def harvest_clearance(
        self, page_url: str, timeout_s: int, opts: BrowserOpts
    ) -> HarvestedContext:
        # nodriver manages its own event loop; run the coroutine on a fresh loop.
        return asyncio.new_event_loop().run_until_complete(
            self._harvest(page_url, timeout_s, opts)
        )

    async def _harvest(
        self, page_url: str, timeout_s: int, opts: BrowserOpts
    ) -> HarvestedContext:
        import nodriver as uc

        browser_args = [
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if opts.viewport:
            # nodriver has no direct viewport kwarg on start; window size hint.
            browser_args.append(
                f"--window-size={opts.viewport.get('width', 1440)},"
                f"{opts.viewport.get('height', 900)}"
            )

        browser = await uc.start(
            headless=opts.headless,
            browser_args=browser_args,
            lang=opts.locale,
        )
        try:
            page = await browser.get(page_url)
            user_agent = await self._user_agent(page)
            clearance = await self._wait_for_clearance(browser, timeout_s)
            cookies = await self._all_cookies(browser)
            return HarvestedContext(
                clearance=clearance,
                user_agent=user_agent,
                cookies=cookies,
                engine=self.name,
            )
        finally:
            try:
                await browser.close()
            except Exception:
                pass

    async def _user_agent(self, page) -> str:
        try:
            ua = await page.evaluate("navigator.userAgent", return_by_value=True)
            if isinstance(ua, str) and ua:
                return ua
        except TypeError:
            # older nodriver signatures may not accept return_by_value
            ua = await page.evaluate("navigator.userAgent")
            if isinstance(ua, str) and ua:
                return ua
        except Exception:
            pass
        return ""

    async def _all_cookies(self, browser) -> dict:
        try:
            from nodriver import cdp

            cookie_list = await browser.main_tab.send(cdp.network.get_cookies())
            return {c.name: c.value for c in (cookie_list or []) if c.name}
        except Exception:
            return {}

    async def _wait_for_clearance(self, browser, timeout_s: int) -> str:
        import time

        from nodriver import cdp

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                cookie_list = await browser.main_tab.send(
                    cdp.network.get_cookies()
                )
            except Exception:
                cookie_list = []
            for c in cookie_list or []:
                if c.name == CLEARANCE_COOKIE and c.value:
                    return c.value
            await asyncio.sleep(2)
        return ""
