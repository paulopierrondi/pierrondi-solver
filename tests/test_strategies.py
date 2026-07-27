from pierrondi_solver.models import ChallengeType, SolveRequest
from pierrondi_solver.strategies.recaptcha_v2_audio import RecaptchaV2AudioStrategy
from pierrondi_solver.strategies.recaptcha_v2_image import RecaptchaV2ImageStrategy
from pierrondi_solver.strategies.recaptcha_v3 import V3_MITIGATION, RecaptchaV3Strategy


def req(challenge_type=ChallengeType.recaptcha_v2):
    return SolveRequest(type=challenge_type, sitekey="k", page_url="https://example.com")


def test_v3_missing_deps_reports(monkeypatch):
    monkeypatch.setattr(
        "pierrondi_solver.strategies.recaptcha_v3._missing_deps",
        lambda: ["playwright"],
    )
    strategy = RecaptchaV3Strategy()
    outcome = strategy.solve(req(ChallengeType.recaptcha_v3))
    assert outcome.solved is False
    assert outcome.reason.startswith("deps_missing")
    assert outcome.cost_usd == 0.0


def test_v3_harvest_success(monkeypatch):
    monkeypatch.setattr(
        RecaptchaV3Strategy, "_harvest_token", lambda self, url, sitekey, timeout: "tok-v3"
    )
    outcome = RecaptchaV3Strategy().solve(req(ChallengeType.recaptcha_v3))
    assert outcome.solved is True
    assert outcome.token == "tok-v3"
    assert outcome.cost_usd == 0.0
    assert "score_note" in outcome.extra


def test_v3_harvest_failure_keeps_guidance(monkeypatch):
    monkeypatch.setattr(
        RecaptchaV3Strategy,
        "_harvest_token",
        lambda self, url, sitekey, timeout: "",
    )
    outcome = RecaptchaV3Strategy().solve(req(ChallengeType.recaptcha_v3))
    assert outcome.solved is False
    assert outcome.reason == "v3_no_token_within_timeout"


def test_v3_harvest_exception_reports_reason(monkeypatch):
    def boom(self, url, sitekey, timeout):
        raise RuntimeError("no grecaptcha")

    monkeypatch.setattr(RecaptchaV3Strategy, "_harvest_token", boom)
    outcome = RecaptchaV3Strategy().solve(req(ChallengeType.recaptcha_v3))
    assert outcome.solved is False
    assert outcome.reason.startswith("v3_harvest_failed: RuntimeError")


def test_v3_supports_only_v3():
    strategy = RecaptchaV3Strategy()
    assert strategy.supports(ChallengeType.recaptcha_v3)
    assert not strategy.supports(ChallengeType.recaptcha_v2)


def test_v2_audio_missing_deps_reports_clearly(monkeypatch):
    # deps ARE installed in this venv; simulate their absence
    monkeypatch.setattr(
        "pierrondi_solver.strategies.recaptcha_v2_audio._missing_deps",
        lambda: ["playwright", "faster-whisper"],
    )
    strategy = RecaptchaV2AudioStrategy()
    outcome = strategy.solve(req())
    assert outcome.solved is False
    assert outcome.reason.startswith("deps_missing")
    assert outcome.cost_usd == 0.0


def test_v2_audio_supports_only_v2():
    strategy = RecaptchaV2AudioStrategy()
    assert strategy.supports(ChallengeType.recaptcha_v2)
    assert not strategy.supports(ChallengeType.recaptcha_v3)


def test_v2_image_honest_stub():
    outcome = RecaptchaV2ImageStrategy().solve(req())
    assert outcome.solved is False
    assert outcome.reason.startswith("not_implemented")
