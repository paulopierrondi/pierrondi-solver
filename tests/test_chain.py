from pierrondi_solver.chain import SolverChain
from pierrondi_solver.circuit_breaker import CircuitBreaker
from pierrondi_solver.config import Config
from pierrondi_solver.models import ChallengeType, SolveRequest, StrategyOutcome
from pierrondi_solver.telemetry import Telemetry


class FakeStrategy:
    def __init__(self, name, provider, types, outcome):
        self.name = name
        self.provider = provider
        self._types = types
        self._outcome = outcome

    def supports(self, challenge_type):
        return challenge_type in self._types

    def solve(self, request):
        return self._outcome


def solved_outcome(provider, strategy="fake"):
    return StrategyOutcome(token="TOK", strategy=strategy, provider=provider, latency_ms=10)


def failed_outcome(provider, reason="boom"):
    return StrategyOutcome(strategy="fake", provider=provider, reason=reason)


V2 = {ChallengeType.recaptcha_v2}


def make_chain(tmp_path, provider="auto", strategies=None):
    config = Config(provider=provider, telemetry_db=str(tmp_path / "t.db"))
    return SolverChain(
        config=config,
        breaker=CircuitBreaker(),
        telemetry=Telemetry(config.telemetry_db),
        strategies=strategies,
    )


def req():
    return SolveRequest(type=ChallengeType.recaptcha_v2,
                        sitekey="6Lc_test", page_url="https://example.com/form", lane="B")


def test_first_success_short_circuits(tmp_path):
    strategies = {
        "pierrondi": [FakeStrategy("a", "pierrondi", V2, solved_outcome("pierrondi"))],
        "capsolver": [FakeStrategy("b", "capsolver", V2, solved_outcome("capsolver"))],
    }
    result, error = make_chain(tmp_path, strategies=strategies).solve(req())
    assert error is None
    assert result.provider == "pierrondi"
    assert result.token == "TOK"


def test_fallback_on_failure(tmp_path):
    strategies = {
        "pierrondi": [FakeStrategy("a", "pierrondi", V2, failed_outcome("pierrondi"))],
        "capsolver": [FakeStrategy("b", "capsolver", V2, solved_outcome("capsolver"))],
    }
    result, error = make_chain(tmp_path, strategies=strategies).solve(req())
    assert error is None
    assert result.provider == "capsolver"


def test_all_fail_returns_unsolved_with_attempts(tmp_path):
    strategies = {
        "pierrondi": [FakeStrategy("a", "pierrondi", V2, failed_outcome("pierrondi", "r1"))],
        "capsolver": [FakeStrategy("b", "capsolver", V2, failed_outcome("capsolver", "r2"))],
    }
    chain = make_chain(tmp_path, provider="auto", strategies=strategies)
    chain.config.provider = "auto"
    chain.config.chain = lambda: ["pierrondi", "capsolver"]
    result, error = chain.solve(req())
    assert result is None
    assert error.error == "unsolved"
    assert "r1" in error.reason and "r2" in error.reason
    assert error.fallback_recommended


def test_breaker_open_skips_provider(tmp_path):
    strategies = {
        "pierrondi": [FakeStrategy("a", "pierrondi", V2, solved_outcome("pierrondi"))],
        "capsolver": [FakeStrategy("b", "capsolver", V2, solved_outcome("capsolver"))],
    }
    chain = make_chain(tmp_path, strategies=strategies)
    for _ in range(5):
        chain.breaker.record("pierrondi", success=False)
    result, _ = chain.solve(req())
    assert result.provider == "capsolver"


def test_deps_missing_does_not_burn_breaker(tmp_path):
    outcome = StrategyOutcome(strategy="v2_audio", provider="pierrondi",
                              reason="deps_missing: playwright")
    strategies = {
        "pierrondi": [FakeStrategy("a", "pierrondi", V2, outcome)],
        "capsolver": [FakeStrategy("b", "capsolver", V2, solved_outcome("capsolver"))],
    }
    chain = make_chain(tmp_path, strategies=strategies)
    result, _ = chain.solve(req())
    assert result.provider == "capsolver"
    stats = chain.breaker.stats("pierrondi")
    assert stats["samples"] == 0  # unavailable-deps is not a solve failure


def test_unsupported_type_skips_strategy(tmp_path):
    strategies = {
        "pierrondi": [FakeStrategy("a", "pierrondi", {ChallengeType.hcaptcha},
                                   solved_outcome("pierrondi"))],
    }
    chain = make_chain(tmp_path, provider="pierrondi", strategies=strategies)
    result, error = chain.solve(req())
    assert result is None
    assert "no providers" in error.reason or error.attempts == []


def test_specific_provider_config(tmp_path):
    strategies = {
        "capsolver": [FakeStrategy("b", "capsolver", V2, solved_outcome("capsolver"))],
    }
    chain = make_chain(tmp_path, provider="capsolver", strategies=strategies)
    result, _ = chain.solve(req())
    assert result.provider == "capsolver"


def test_attempts_logged_to_telemetry(tmp_path):
    strategies = {
        "pierrondi": [FakeStrategy("a", "pierrondi", V2, solved_outcome("pierrondi"))],
    }
    chain = make_chain(tmp_path, provider="pierrondi", strategies=strategies)
    chain.solve(req())
    summary = chain.telemetry.summary()
    assert summary["attempts"] == 1
    assert summary["solved"] == 1
