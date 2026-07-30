"""Tests for the Turnstile local harvest strategy.

CI-safe: no browser launch, no network. The Playwright-driving
``_harvest_token`` is monkeypatched; deps-missing is simulated.
"""
from __future__ import annotations

from pierrondi_solver.models import ChallengeType, SolveRequest
from pierrondi_solver.strategies.turnstile import TurnstileStrategy


def req():
    return SolveRequest(
        type=ChallengeType.turnstile, sitekey="k", page_url="https://example.com"
    )


def test_supports_only_turnstile():
    s = TurnstileStrategy()
    assert s.supports(ChallengeType.turnstile)
    assert not s.supports(ChallengeType.recaptcha_v2)
    assert not s.supports(ChallengeType.recaptcha_v3)
    assert not s.supports(ChallengeType.hcaptcha)
    assert not s.supports(ChallengeType.cloudflare)


def test_missing_deps_reports(monkeypatch):
    monkeypatch.setattr(
        "pierrondi_solver.strategies.turnstile._missing_deps",
        lambda: ["playwright"],
    )
    outcome = TurnstileStrategy().solve(req())
    assert outcome.solved is False
    assert outcome.reason.startswith("deps_missing")
    assert outcome.cost_usd == 0.0


def test_harvest_success(monkeypatch):
    monkeypatch.setattr(
        TurnstileStrategy, "_harvest_token", lambda self, url, timeout, proxy="": "tok-123"
    )
    outcome = TurnstileStrategy().solve(req())
    assert outcome.solved is True
    assert outcome.token == "tok-123"
    assert outcome.strategy == "turnstile_harvest"
    assert outcome.provider == "pierrondi"
    assert outcome.cost_usd == 0.0


def test_harvest_empty_token(monkeypatch):
    monkeypatch.setattr(TurnstileStrategy, "_harvest_token", lambda self, url, timeout, proxy="": "")
    outcome = TurnstileStrategy().solve(req())
    assert outcome.solved is False
    assert outcome.reason == "turnstile_no_token_within_timeout"


def test_harvest_exception_reports_reason(monkeypatch):
    def boom(self, url, timeout, proxy=""):
        raise RuntimeError("browser crashed")

    monkeypatch.setattr(TurnstileStrategy, "_harvest_token", boom)
    outcome = TurnstileStrategy().solve(req())
    assert outcome.solved is False
    assert outcome.reason.startswith("turnstile_failed: RuntimeError")
    assert "browser crashed" in outcome.reason


def test_reason_is_bounded(monkeypatch):
    def boom(self, url, timeout, proxy=""):
        raise RuntimeError("x" * 1000)

    monkeypatch.setattr(TurnstileStrategy, "_harvest_token", boom)
    outcome = TurnstileStrategy().solve(req())
    assert len(outcome.reason) <= 400
