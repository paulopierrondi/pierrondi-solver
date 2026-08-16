"""Browser backend contracts.

A ``BrowserBackend`` abstracts the engine used to harvest challenge clearance
(e.g. Cloudflare ``cf_clearance``). The strategy depends on this interface
rather than on a concrete engine, so additional engines (Firefox, WebKit,
camoufox, nodriver, ...) can be added without rewriting the strategy.

Heavy deps (playwright) stay optional/lazy: a backend reports ``deps_missing``
and the chain skips it without burning breaker budget — the same pattern the
codebase already uses for ``_playwright_missing``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


_CLOUDFLARE_INTERSTITIAL_MARKERS = (
    "just a moment",
    "checking your browser",
    "verify you are human",
    "performing security verification",
    "enable javascript and cookies to continue",
    "cf_chl",
)


def cloudflare_interstitial_text_present(title: str, body: str) -> bool:
    """Return whether rendered text still represents a CF interstitial."""

    rendered = f"{title}\n{body[:20_000]}".lower()
    return any(marker in rendered for marker in _CLOUDFLARE_INTERSTITIAL_MARKERS)


def cloudflare_interstitial_present(page: Any) -> bool:
    """Fail closed until the harvesting browser has left the CF interstitial.

    A ``cf_clearance`` cookie can appear before Cloudflare finishes its redirect.
    Returning it at that instant produces a false ``solved`` result: the caller
    replays the cookie while the browser is still bound to the challenge page.
    """

    try:
        title = str(page.title() or "")
        body = str(page.locator("body").inner_text(timeout=2_000) or "")
    except Exception:
        return True
    return cloudflare_interstitial_text_present(title, body)


@dataclass
class BrowserOpts:
    """Launch/context options. Defaults reproduce the original hardcoded
    Chromium fingerprint while keeping unattended runs silent by default."""

    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
    viewport: dict = field(default_factory=lambda: {"width": 1440, "height": 900})
    locale: str = "en-US"
    headless: bool = True
    # Optional proxy connect string (e.g. "http://user:pass@host:port").
    # When set, the backend routes the clearance harvest through this proxy so
    # the resulting cf_clearance is bound to a controlled IP, not the host IP.
    proxy: str = ""


@dataclass
class HarvestedContext:
    """Result of a successful clearance harvest."""

    clearance: str
    user_agent: str
    cookies: dict
    engine: str
    # Cleared page as rendered inside the harvesting browser; lets callers
    # with a different TLS fingerprint consume content without replaying the
    # fingerprint-bound cf_clearance cookie. Optional: engines may omit it.
    page_html: str = ""


class BrowserBackend(Protocol):
    """Engine-agnostic clearance harvester.

    Implementations MUST:
    - expose ``name`` (e.g. ``"chromium"``, ``"firefox"``);
    - report missing optional deps via ``deps_missing`` (empty list when ready);
    - raise on harvest failure; return a populated ``HarvestedContext`` on success.
    """

    name: str
    supports_proxy: bool

    def deps_missing(self) -> list[str]: ...

    def harvest_clearance(
        self, page_url: str, timeout_s: int, opts: BrowserOpts
    ) -> HarvestedContext: ...
