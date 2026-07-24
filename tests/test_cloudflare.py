from pierrondi_solver.models import ChallengeType, SolveRequest
from pierrondi_solver.strategies.cloudflare_clearance import CloudflareClearanceStrategy


def req():
    return SolveRequest(type=ChallengeType.cloudflare, sitekey="",
                        page_url="https://example.com/protected", timeout_s=5)


def test_supports_only_cloudflare():
    strategy = CloudflareClearanceStrategy()
    assert strategy.supports(ChallengeType.cloudflare)
    assert not strategy.supports(ChallengeType.recaptcha_v2)
    assert not strategy.supports(ChallengeType.turnstile)


def test_missing_playwright_reports_deps_missing(monkeypatch):
    # playwright IS installed in this venv; simulate its absence at the backend.
    # After the BrowserBackend extraction, deps are reported by the backend.
    monkeypatch.setattr(
        "pierrondi_solver.browser.chromium._playwright_missing", lambda: True
    )
    outcome = CloudflareClearanceStrategy().solve(req())
    assert outcome.solved is False
    assert outcome.reason.startswith("deps_missing")
    assert outcome.cost_usd == 0.0


def test_headful_default_for_managed_challenges():
    assert CloudflareClearanceStrategy().headless is False
