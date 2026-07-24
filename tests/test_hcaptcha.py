"""Tests for the hCaptcha local audio strategy (vetor A).

CI-safe: no browser launch, no network. Deps-missing and cookie-missing paths
are exercised via monkeypatch.
"""
from __future__ import annotations

from pierrondi_solver.models import ChallengeType, SolveRequest
from pierrondi_solver.strategies.hcaptcha import HCaptchaAudioStrategy


def req():
    return SolveRequest(type=ChallengeType.hcaptcha, sitekey="k", page_url="https://example.com")


def test_supports_only_hcaptcha():
    s = HCaptchaAudioStrategy(accessibility_cookie="cookie")
    assert s.supports(ChallengeType.hcaptcha)
    assert not s.supports(ChallengeType.recaptcha_v2)
    assert not s.supports(ChallengeType.turnstile)


def test_missing_deps_reports(monkeypatch):
    monkeypatch.setattr(
        "pierrondi_solver.strategies.hcaptcha._missing_deps",
        lambda: ["playwright", "faster-whisper"],
    )
    outcome = HCaptchaAudioStrategy(accessibility_cookie="cookie").solve(req())
    assert outcome.solved is False
    assert outcome.reason.startswith("deps_missing")
    assert outcome.cost_usd == 0.0


def test_missing_accessibility_cookie_reports_deps_missing():
    # deps present (venv has them) but no cookie -> deps_missing
    outcome = HCaptchaAudioStrategy(accessibility_cookie="").solve(req())
    assert outcome.solved is False
    assert outcome.reason.startswith("deps_missing")
    assert "accessibility" in outcome.reason.lower()
    assert outcome.cost_usd == 0.0


def test_strategy_name_and_provider():
    s = HCaptchaAudioStrategy(accessibility_cookie="cookie")
    assert s.name == "hcaptcha_audio"
    assert s.provider == "pierrondi"
