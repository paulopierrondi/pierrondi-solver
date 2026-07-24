"""Browser backend registry.

``get_browser(name)`` returns a backend instance for the requested engine.
Unknown engine names raise ``ValueError``; callers (strategy/chain) translate
that into a ``deps_missing`` reason so the chain skips gracefully.
"""
from __future__ import annotations

from .base import BrowserBackend, BrowserOpts, HarvestedContext
from .camoufox_backend import CamoufoxBackend
from .chromium import ChromiumBackend
from .firefox import FirefoxBackend
from .nodriver_backend import NodriverBackend

BACKENDS: dict[str, type] = {
    "chromium": ChromiumBackend,
    "firefox": FirefoxBackend,
    "nodriver": NodriverBackend,
    "camoufox": CamoufoxBackend,
}

__all__ = [
    "BACKENDS",
    "BrowserBackend",
    "BrowserOpts",
    "HarvestedContext",
    "get_browser",
    "browser_deps_missing",
]


def get_browser(name: str) -> BrowserBackend:
    """Return a backend instance for ``name``. Raises ``ValueError`` for an
    unknown engine so the strategy can surface ``deps_missing: unknown_engine``."""
    key = (name or "").strip().lower()
    cls = BACKENDS.get(key)
    if cls is None:
        raise ValueError(f"unknown browser engine: {name!r}")
    return cls()


def browser_deps_missing(name: str) -> list[str]:
    """Return the deps-missing hints for ``name`` without raising. For an
    unknown engine, the hint names it so the chain can skip gracefully."""
    try:
        return get_browser(name).deps_missing()
    except ValueError:
        return [f"unknown_engine: {name}"]
