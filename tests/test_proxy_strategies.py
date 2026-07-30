"""Tests for the proxy layer on token-harvest strategies (turnstile + v3)
and the playwright_proxy helper. Fixture-only, no network, no browser."""
from __future__ import annotations

from pierrondi_solver.models import ChallengeType, SolveRequest
from pierrondi_solver.proxy import StaticProxyBackend, playwright_proxy
from pierrondi_solver.strategies.recaptcha_v3 import RecaptchaV3Strategy
from pierrondi_solver.strategies.turnstile import TurnstileStrategy


def req(challenge_type=ChallengeType.turnstile):
    return SolveRequest(type=challenge_type, sitekey="k", page_url="https://example.com")


# --- playwright_proxy helper ---


def test_playwright_proxy_empty():
    assert playwright_proxy("") == {}


def test_playwright_proxy_host_only():
    assert playwright_proxy("http://gw.example:8080") == {"server": "http://gw.example:8080"}


def test_playwright_proxy_with_credentials():
    out = playwright_proxy("http://user:pass@gw.example:12323")
    assert out == {"server": "http://gw.example:12323", "username": "user", "password": "pass"}


def test_playwright_proxy_socks5():
    out = playwright_proxy("socks5://gw.example:1080")
    assert out == {"server": "socks5://gw.example:1080"}


def test_playwright_proxy_garbage_is_empty():
    assert playwright_proxy("not-a-url") == {}


# --- turnstile proxy wiring ---


def test_turnstile_uses_configured_proxy(monkeypatch):
    captured = {}

    def fake(self, url, timeout, proxy=""):
        captured["proxy"] = proxy
        return "tok"

    monkeypatch.setattr(TurnstileStrategy, "_harvest_token", fake)
    backend = StaticProxyBackend("http://user:pass@gw.example:12323")
    outcome = TurnstileStrategy(proxy_backend=backend).solve(req())
    assert outcome.solved is True
    assert captured["proxy"] == "http://user:pass@gw.example:12323"
    assert outcome.extra["proxy"]["kind"] == "static"
    assert len(outcome.extra["proxy"]["fingerprint"]) == 8
    assert "user" not in str(outcome.extra) and "pass" not in str(outcome.extra)


def test_turnstile_no_proxy_configured_uses_host(monkeypatch):
    captured = {}

    def fake(self, url, timeout, proxy=""):
        captured["proxy"] = proxy
        return "tok"

    monkeypatch.setattr(TurnstileStrategy, "_harvest_token", fake)
    monkeypatch.delenv("SOLVER_PROXY", raising=False)
    monkeypatch.delenv("SOLVER_PROXY_ENDPOINT", raising=False)
    outcome = TurnstileStrategy(proxy_backend=StaticProxyBackend("")).solve(req())
    assert outcome.solved is True
    assert captured["proxy"] == ""
    assert "proxy" not in outcome.extra


def test_turnstile_fails_closed_when_proxy_required_but_unavailable(monkeypatch):
    monkeypatch.setenv("SOLVER_PROXY", "http://gw.example:8080")
    outcome = TurnstileStrategy(proxy_backend=StaticProxyBackend("")).solve(req())
    assert outcome.solved is False
    assert outcome.reason == "deps_missing: proxy_unavailable"


# --- v3 proxy wiring ---


def test_v3_uses_configured_proxy(monkeypatch):
    captured = {}

    def fake(self, url, sitekey, timeout, proxy=""):
        captured["proxy"] = proxy
        return "tok"

    monkeypatch.setattr(RecaptchaV3Strategy, "_harvest_token", fake)
    backend = StaticProxyBackend("socks5://gw.example:1080")
    outcome = RecaptchaV3Strategy(proxy_backend=backend).solve(req(ChallengeType.recaptcha_v3))
    assert outcome.solved is True
    assert captured["proxy"] == "socks5://gw.example:1080"
    assert outcome.extra["proxy"]["kind"] == "static"


def test_v3_fails_closed_when_proxy_required_but_unavailable(monkeypatch):
    monkeypatch.setenv("SOLVER_PROXY_ENDPOINT", "http://rotate.example/get")
    outcome = RecaptchaV3Strategy(proxy_backend=StaticProxyBackend("")).solve(
        req(ChallengeType.recaptcha_v3)
    )
    assert outcome.solved is False
    assert outcome.reason == "deps_missing: proxy_unavailable"


def test_env_backend_is_used_when_none_injected(monkeypatch):
    monkeypatch.setenv("SOLVER_PROXY", "http://gw.example:9999")
    captured = {}

    def fake(self, url, timeout, proxy=""):
        captured["proxy"] = proxy
        return "tok"

    monkeypatch.setattr(TurnstileStrategy, "_harvest_token", fake)
    outcome = TurnstileStrategy().solve(req())
    assert outcome.solved is True
    assert captured["proxy"] == "http://gw.example:9999"
