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
from typing import Protocol


@dataclass
class BrowserOpts:
    """Launch/context options. Defaults reproduce the original hardcoded
    Chromium fingerprint exactly, so behavior is unchanged when no override
    is supplied."""

    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
    viewport: dict = field(default_factory=lambda: {"width": 1440, "height": 900})
    locale: str = "en-US"
    headless: bool = False
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
