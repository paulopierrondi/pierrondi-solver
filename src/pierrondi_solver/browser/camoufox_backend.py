"""camoufox backend — hardened, anti-detect Firefox.

``camoufox`` is a Firefox fork engineered to evade fingerprinting: spoofed
canvas/WebGL/fonts, consistent fingerprints, network header spoofing. It is a
drop-in replacement for Playwright's Firefox API (``camoufox.sync_api.Camoufox``)
so the harvest algorithm mirrors the Playwright backends.

Trade-offs vs the Playwright Firefox backend:
- Pro: fingerprint spoofing out of the box; materially stronger against
  advanced managed challenges than vanilla Firefox.
- Con: separate browser binary (``python -m camoufox fetch``); heavier dep.
- Dep: optional (``pip install '.[camoufox]'``); missing -> ``deps_missing``.
"""
from __future__ import annotations

import time

from .base import BrowserOpts, HarvestedContext

CLEARANCE_COOKIE = "cf_clearance"


def _camoufox_missing() -> bool:
    try:
        import camoufox  # noqa: F401

        return False
    except ImportError:
        return True


class CamoufoxBackend:
    """Hardened anti-detect Firefox clearance harvester (drop-in Playwright)."""

    name = "camoufox"
    supports_proxy = True

    def deps_missing(self) -> list[str]:
        if _camoufox_missing():
            return ["pip install '.[camoufox]' + python -m camoufox fetch"]
        return []

    def harvest_clearance(
        self, page_url: str, timeout_s: int, opts: BrowserOpts
    ) -> HarvestedContext:
        from camoufox.sync_api import Camoufox

        deadline = time.monotonic() + timeout_s
        # Camoufox manages its own fingerprint/UA spoofing; we pass only
        # viewport/locale/headless to keep its consistency guarantees intact
        # (overriding user_agent would break the spoofed fingerprint chain).
        launch_kwargs: dict = {
            "headless": opts.headless,
            "viewport": opts.viewport or None,
            "locale": opts.locale or None,
        }
        if opts.proxy:
            launch_kwargs["proxy"] = {"server": opts.proxy}
            launch_kwargs["geoip"] = True
        with Camoufox(**launch_kwargs) as browser:
            context = browser.new_context()
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
                    user_agent="",
                    cookies={},
                    engine=self.name,
                )
            finally:
                browser.close()
