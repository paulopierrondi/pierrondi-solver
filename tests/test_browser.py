"""Tests for the browser backend abstraction and multi-engine support.

These tests are CI-safe: no real browser launch and no network. They cover the
contracts the chain depends on (deps_missing reporting, engine selection,
strategy delegation) and the backward-compatible default (Chromium).
"""
from __future__ import annotations

from pierrondi_solver.browser import (
    BACKENDS,
    browser_deps_missing,
    get_browser,
)
from pierrondi_solver.browser.base import HarvestedContext
from pierrondi_solver.browser.chromium import ChromiumBackend
from pierrondi_solver.browser.firefox import FirefoxBackend
from pierrondi_solver.browser.nodriver_backend import NodriverBackend
from pierrondi_solver.browser.camoufox_backend import CamoufoxBackend
from pierrondi_solver.models import ChallengeType, SolveRequest
from pierrondi_solver.strategies.cloudflare_clearance import (
    CloudflareClearanceStrategy,
    build_cloudflare_strategy,
)


def _req():
    return SolveRequest(
        type=ChallengeType.cloudflare,
        sitekey="",
        page_url="https://example.com/protected",
        timeout_s=5,
    )


# --- registry / factory -------------------------------------------------

def test_registry_has_chromium_and_firefox():
    assert "chromium" in BACKENDS
    assert "firefox" in BACKENDS


def test_get_browser_returns_instances():
    assert isinstance(get_browser("chromium"), ChromiumBackend)
    assert isinstance(get_browser("firefox"), FirefoxBackend)


def test_get_browser_is_case_insensitive_and_trimmed():
    assert isinstance(get_browser("  Firefox  "), FirefoxBackend)
    assert isinstance(get_browser("CHROMIUM"), ChromiumBackend)


def test_get_browser_unknown_raises():
    try:
        get_browser("webkit")
    except ValueError as exc:
        assert "webkit" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown engine")


def test_browser_deps_missing_unknown_engine_reports_hint():
    hints = browser_deps_missing("webkit")
    assert any("webkit" in h for h in hints)


# --- chromium backend ---------------------------------------------------

def test_chromium_backend_name():
    assert ChromiumBackend().name == "chromium"


def test_chromium_missing_deps_reports(monkeypatch):
    monkeypatch.setattr(
        "pierrondi_solver.browser.chromium._playwright_missing", lambda: True
    )
    missing = ChromiumBackend().deps_missing()
    assert missing  # non-empty
    assert any("local-solve" in m or "playwright" in m for m in missing)


# --- firefox backend ----------------------------------------------------

def test_firefox_backend_name():
    assert FirefoxBackend().name == "firefox"


def test_firefox_missing_deps_reports(monkeypatch):
    monkeypatch.setattr(
        "pierrondi_solver.browser.firefox._playwright_missing", lambda: True
    )
    monkeypatch.setattr(
        "pierrondi_solver.browser.firefox._firefox_browser_missing", lambda: True
    )
    missing = FirefoxBackend().deps_missing()
    assert missing
    assert any("local-solve" in m or "playwright" in m for m in missing)
    assert any("firefox" in m for m in missing)


# --- nodriver backend ---------------------------------------------------

def test_nodriver_backend_name():
    assert NodriverBackend().name == "nodriver"


def test_nodriver_in_registry():
    assert "nodriver" in BACKENDS
    assert isinstance(get_browser("nodriver"), NodriverBackend)


def test_nodriver_missing_deps_reports(monkeypatch):
    monkeypatch.setattr(
        "pierrondi_solver.browser.nodriver_backend._nodriver_missing", lambda: True
    )
    missing = NodriverBackend().deps_missing()
    assert missing
    assert any("nodriver" in m for m in missing)


def test_nodriver_present_deps_empty(monkeypatch):
    # simulate nodriver being importable
    monkeypatch.setattr(
        "pierrondi_solver.browser.nodriver_backend._nodriver_missing", lambda: False
    )
    assert NodriverBackend().deps_missing() == []


# --- camoufox backend ---------------------------------------------------

def test_camoufox_backend_name():
    assert CamoufoxBackend().name == "camoufox"


def test_camoufox_in_registry():
    assert "camoufox" in BACKENDS
    assert isinstance(get_browser("camoufox"), CamoufoxBackend)


def test_camoufox_missing_deps_reports(monkeypatch):
    monkeypatch.setattr(
        "pierrondi_solver.browser.camoufox_backend._camoufox_missing", lambda: True
    )
    missing = CamoufoxBackend().deps_missing()
    assert missing
    assert any("camoufox" in m for m in missing)


def test_camoufox_present_deps_empty(monkeypatch):
    monkeypatch.setattr(
        "pierrondi_solver.browser.camoufox_backend._camoufox_missing", lambda: False
    )
    assert CamoufoxBackend().deps_missing() == []


# --- strategy delegation ------------------------------------------------

CLEARANCE_COOKIE_NAME = "cf_clearance"


class _FakeBackend:
    """Deterministic backend that returns a clearance without launching a browser."""

    name = "fake"
    supports_proxy = True

    def __init__(self, clearance: str = "CF_CLEARANCE_TOKEN") -> None:
        self._clearance = clearance
        self.harvest_called = False
        self.opts = None

    def deps_missing(self) -> list[str]:
        return []

    def harvest_clearance(self, page_url, timeout_s, opts):
        self.harvest_called = True
        self.opts = opts
        return HarvestedContext(
            clearance=self._clearance,
            user_agent="FAKE_UA",
            cookies={ CLEARANCE_COOKIE_NAME: self._clearance},
            engine=self.name,
        )


def test_strategy_accepts_injected_backend_and_solves():
    backend = _FakeBackend(clearance="TOKEN_123")
    strategy = CloudflareClearanceStrategy(backend=backend)
    outcome = strategy.solve(_req())
    assert outcome.solved is True
    assert outcome.token == "TOKEN_123"
    assert outcome.cost_usd == 0.0
    assert outcome.extra["engine"] == "fake"
    assert outcome.extra["user_agent"] == "FAKE_UA"
    assert outcome.extra["cookies"]["cf_clearance"] == "TOKEN_123"
    assert backend.harvest_called is True


def test_strategy_resolves_proxy_per_lane_without_exposing_credentials():
    class _ProxyBackend:
        def __init__(self):
            self.lane = None

        def resolve(self, lane="default"):
            from pierrondi_solver.proxy import ProxyConfig

            self.lane = lane
            return ProxyConfig(
                connect_string="http://user:password@proxy.example:8080",
                kind="sticky",
            )

    backend = _FakeBackend(clearance="TOKEN_123")
    proxy_backend = _ProxyBackend()
    request = _req().model_copy(update={"lane": "account-a"})
    outcome = CloudflareClearanceStrategy(
        backend=backend,
        proxy_backend=proxy_backend,
        proxy_required=True,
    ).solve(request)

    assert outcome.solved is True
    assert proxy_backend.lane == "account-a"
    assert backend.opts.proxy == "http://user:password@proxy.example:8080"
    assert outcome.extra["proxy"]["kind"] == "sticky"
    assert len(outcome.extra["proxy"]["fingerprint"]) == 8
    assert "user" not in str(outcome.extra["proxy"])
    assert "password" not in str(outcome.extra["proxy"])


def test_strategy_fails_closed_when_required_proxy_is_unavailable():
    class _UnavailableProxy:
        def resolve(self, lane="default"):
            return None

    outcome = CloudflareClearanceStrategy(
        backend=_FakeBackend(),
        proxy_backend=_UnavailableProxy(),
        proxy_required=True,
    ).solve(_req())
    assert outcome.solved is False
    assert outcome.reason == "deps_missing: proxy_unavailable"


def test_strategy_rejects_proxy_for_backend_without_safe_support():
    from pierrondi_solver.proxy import StaticProxyBackend

    backend = _FakeBackend()
    backend.name = "no-proxy"
    backend.supports_proxy = False
    outcome = CloudflareClearanceStrategy(
        backend=backend,
        proxy_backend=StaticProxyBackend("http://proxy.example:8080"),
        proxy_required=True,
    ).solve(_req())
    assert outcome.solved is False
    assert outcome.reason == "deps_missing: no-proxy: proxy_not_supported"


def test_strategy_reports_deps_missing_from_backend():
    class _MissingBackend:
        name = "missing-engine"

        def deps_missing(self) -> list[str]:
            return ["install-hint-1", "install-hint-2"]

        def harvest_clearance(self, page_url, timeout_s, opts):  # pragma: no cover
            raise AssertionError("should not be called when deps missing")

    strategy = CloudflareClearanceStrategy(backend=_MissingBackend())
    outcome = strategy.solve(_req())
    assert outcome.solved is False
    assert outcome.reason.startswith("deps_missing")
    assert "missing-engine" in outcome.reason
    assert outcome.cost_usd == 0.0


def test_strategy_translates_harvest_exception():
    class _ExplodingBackend:
        name = "boom"

        def deps_missing(self) -> list[str]:
            return []

        def harvest_clearance(self, page_url, timeout_s, opts):
            raise RuntimeError("navigation timeout")

    strategy = CloudflareClearanceStrategy(backend=_ExplodingBackend())
    outcome = strategy.solve(_req())
    assert outcome.solved is False
    assert outcome.reason.startswith("cf_clearance_failed")
    assert "RuntimeError" in outcome.reason


def test_strategy_reports_timeout_when_no_clearance():
    class _EmptyBackend:
        name = "empty"

        def deps_missing(self) -> list[str]:
            return []

        def harvest_clearance(self, page_url, timeout_s, opts):
            return HarvestedContext(
                clearance="", user_agent="UA", cookies={}, engine="empty"
            )

    strategy = CloudflareClearanceStrategy(backend=_EmptyBackend())
    outcome = strategy.solve(_req())
    assert outcome.solved is False
    assert outcome.reason == "cf_clearance_not_granted_within_timeout"


# --- backward compatibility --------------------------------------------

def test_default_backend_is_chromium():
    strategy = CloudflareClearanceStrategy()
    assert strategy.backend.name == "chromium"


def test_build_cloudflare_strategy_uses_engine():
    assert build_cloudflare_strategy("firefox").backend.name == "firefox"
    assert build_cloudflare_strategy("chromium").backend.name == "chromium"


def test_build_cloudflare_strategy_unknown_engine_reports_deps_missing():
    # Unknown engine must not crash construction; it surfaces via deps_missing.
    strategy = build_cloudflare_strategy("webkit")
    outcome = strategy.solve(_req())
    assert outcome.solved is False
    assert outcome.reason.startswith("deps_missing")
    assert "unknown_engine" in outcome.reason or "webkit" in outcome.reason


def test_strategy_supports_only_cloudflare():
    strategy = CloudflareClearanceStrategy()
    assert strategy.supports(ChallengeType.cloudflare)
    assert not strategy.supports(ChallengeType.recaptcha_v2)
    assert not strategy.supports(ChallengeType.turnstile)
