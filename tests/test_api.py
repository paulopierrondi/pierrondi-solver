from fastapi.testclient import TestClient

from pierrondi_solver.chain import SolverChain
from pierrondi_solver.circuit_breaker import CircuitBreaker
from pierrondi_solver.config import Config
from pierrondi_solver.main import create_app
from pierrondi_solver.models import ChallengeType, StrategyOutcome
from pierrondi_solver.telemetry import Telemetry


class FakeStrategy:
    name = "fake"
    provider = "pierrondi"

    def __init__(self, outcome, supported_type=ChallengeType.recaptcha_v2):
        self._outcome = outcome
        self._supported_type = supported_type

    def supports(self, challenge_type):
        return challenge_type == self._supported_type

    def solve(self, request):
        return self._outcome


def make_client(tmp_path, outcome, supported_type=ChallengeType.recaptcha_v2):
    config = Config(provider="pierrondi", telemetry_db=str(tmp_path / "api.db"))
    chain = SolverChain(
        config=config,
        breaker=CircuitBreaker(),
        telemetry=Telemetry(config.telemetry_db),
        strategies={"pierrondi": [FakeStrategy(outcome, supported_type)]},
    )
    return TestClient(create_app(chain))


PAYLOAD = {"type": "recaptcha_v2", "sitekey": "6Lc_test",
           "page_url": "https://example.com/form", "lane": "B"}


def test_health(tmp_path):
    client = make_client(tmp_path, StrategyOutcome())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["providers"] == ["pierrondi"]


def test_solve_success(tmp_path):
    outcome = StrategyOutcome(token="TOK123", strategy="v2_audio",
                              provider="pierrondi", latency_ms=42)
    client = make_client(tmp_path, outcome)
    resp = client.post("/solve", json=PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"] == "TOK123"
    assert body["strategy"] == "v2_audio"
    assert body["cost_usd"] == 0.0
    assert body["extra"]["artifact_policy"] == {
        "purpose": "generic",
        "operation_id": "",
        "attempt": 1,
        "consumption": "single_use",
        "must_not_reuse_across_purposes": True,
    }


def test_solve_carries_stage_aware_artifact_policy(tmp_path):
    outcome = StrategyOutcome(token="TOK123", strategy="v2_audio",
                              provider="pierrondi", latency_ms=42)
    client = make_client(tmp_path, outcome)
    resp = client.post(
        "/solve",
        json={
            **PAYLOAD,
            "purpose": "read_only",
            "operation_id": "booking-check-001",
            "attempt": 2,
        },
    )
    assert resp.status_code == 200
    policy = resp.json()["extra"]["artifact_policy"]
    assert policy["purpose"] == "read_only"
    assert policy["operation_id"] == "booking-check-001"
    assert policy["attempt"] == 2
    assert policy["consumption"] == "single_use"


def test_cloudflare_artifact_is_session_bound(tmp_path):
    outcome = StrategyOutcome(
        token="CLEARANCE",
        strategy="cloudflare_clearance",
        provider="pierrondi",
        extra={"cookies": {"cf_clearance": "redacted"}, "user_agent": "test"},
    )
    client = make_client(tmp_path, outcome, ChallengeType.cloudflare)
    payload = {
        "type": "cloudflare",
        "sitekey": "",
        "page_url": "https://example.com/protected",
        "purpose": "authentication",
    }
    resp = client.post("/solve", json=payload)
    assert resp.status_code == 200
    assert (
        resp.json()["extra"]["artifact_policy"]["consumption"]
        == "session_bound"
    )
    assert (
        resp.json()["extra"]["artifact_policy"]["must_not_reuse_across_purposes"]
        is False
    )


def test_solve_unsolved_returns_422(tmp_path):
    outcome = StrategyOutcome(strategy="v2_audio", provider="pierrondi", reason="boom")
    client = make_client(tmp_path, outcome)
    resp = client.post("/solve", json=PAYLOAD)
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "unsolved"
    assert "boom" in body["reason"]
    assert body["fallback_recommended"] is True


def test_solve_rejects_invalid_type(tmp_path):
    client = make_client(tmp_path, StrategyOutcome())
    resp = client.post("/solve", json={**PAYLOAD, "type": "megacaptcha"})
    assert resp.status_code == 422


def test_solve_rejects_missing_sitekey(tmp_path):
    client = make_client(tmp_path, StrategyOutcome())
    bad = {k: v for k, v in PAYLOAD.items() if k != "sitekey"}
    assert client.post("/solve", json=bad).status_code == 422


def test_solve_rejects_unsafe_operation_id_shape(tmp_path):
    client = make_client(tmp_path, StrategyOutcome())
    assert client.post(
        "/solve", json={**PAYLOAD, "operation_id": "contains spaces"}
    ).status_code == 422


def test_metrics_endpoint(tmp_path):
    outcome = StrategyOutcome(token="TOK", strategy="v2_audio", provider="pierrondi")
    client = make_client(tmp_path, outcome)
    client.post("/solve", json=PAYLOAD)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["attempts"] == 1
    assert body["by_provider"]["pierrondi"]["solved"] == 1
