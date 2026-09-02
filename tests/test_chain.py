from pierrondi_solver.chain import SolverChain
from pierrondi_solver.circuit_breaker import CircuitBreaker
from pierrondi_solver.config import Config
from pierrondi_solver.models import (
    ChallengeType,
    SolvePurpose,
    SolveRequest,
    StrategyOutcome,
)
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


# --- chain deadline + transient retry ---


class _Clock:
    def __init__(self):
        self.now = 1000.0


class SeqStrategy:
    """Returns queued outcomes in order and can burn fake-clock time per call."""

    def __init__(self, name, provider, types, outcomes, clock=None, tick=0):
        self.name = name
        self.provider = provider
        self._types = types
        self._outcomes = list(outcomes)
        self._clock = clock
        self._tick = tick
        self.calls = 0
        self.seen_timeouts = []

    def supports(self, challenge_type):
        return challenge_type in self._types

    def solve(self, request):
        self.calls += 1
        self.seen_timeouts.append(request.timeout_s)
        if self._clock is not None:
            self._clock.now += self._tick
        if len(self._outcomes) > 1:
            return self._outcomes.pop(0)
        return self._outcomes[0]


def _patch_clock(monkeypatch, clock):
    monkeypatch.setattr("pierrondi_solver.chain.time.monotonic", lambda: clock.now)


def test_chain_deadline_stops_advancing(tmp_path, monkeypatch):
    clock = _Clock()
    _patch_clock(monkeypatch, clock)
    local = SeqStrategy("a", "pierrondi", V2, [failed_outcome("pierrondi", "boom")],
                        clock=clock, tick=130)  # burns the 120s budget
    paid = SeqStrategy("b", "capsolver", V2, [solved_outcome("capsolver")])
    strategies = {"pierrondi": [local], "capsolver": [paid]}
    chain = make_chain(tmp_path, strategies=strategies)
    chain.config.chain = lambda: ["pierrondi", "capsolver"]
    result, error = chain.solve(req())
    assert result is None
    assert "chain_deadline_exceeded" in error.reason
    assert paid.calls == 0  # never attempted after the budget ran out


def test_attempt_timeout_uses_remaining_budget(tmp_path, monkeypatch):
    clock = _Clock()
    _patch_clock(monkeypatch, clock)
    local = SeqStrategy("a", "pierrondi", V2, [failed_outcome("pierrondi", "boom")],
                        clock=clock, tick=100)
    paid = SeqStrategy("b", "capsolver", V2, [solved_outcome("capsolver")])
    strategies = {"pierrondi": [local], "capsolver": [paid]}
    chain = make_chain(tmp_path, strategies=strategies)
    chain.config.chain = lambda: ["pierrondi", "capsolver"]
    result, _ = chain.solve(req())  # request timeout_s=120
    assert result.provider == "capsolver"
    assert local.seen_timeouts == [120]
    assert paid.seen_timeouts == [20]  # remaining budget, not the full timeout


def test_transient_failure_retries_local_once(tmp_path):
    local = SeqStrategy("a", "pierrondi", V2, [
        failed_outcome("pierrondi", "v2_image_failed: TimeoutError: boom"),
        solved_outcome("pierrondi"),
    ])
    strategies = {
        "pierrondi": [local],
        "capsolver": [FakeStrategy("b", "capsolver", V2, solved_outcome("capsolver"))],
    }
    chain = make_chain(tmp_path, provider="pierrondi", strategies=strategies)
    result, error = chain.solve(req())
    assert error is None
    assert result.provider == "pierrondi"
    assert local.calls == 2
    summary = chain.telemetry.summary()
    assert summary["attempts"] == 2  # both the failure and the retry logged


def test_transient_retry_visible_in_attempts(tmp_path):
    local = SeqStrategy("a", "pierrondi", V2, [
        failed_outcome("pierrondi", "net::ERR_CONNECTION_REFUSED"),
        failed_outcome("pierrondi", "still down"),
    ])
    strategies = {
        "pierrondi": [local],
        "capsolver": [FakeStrategy("b", "capsolver", V2, failed_outcome("capsolver", "r2"))],
    }
    chain = make_chain(tmp_path, strategies=strategies)
    chain.config.chain = lambda: ["pierrondi", "capsolver"]
    result, error = chain.solve(req())
    assert result is None  # retry failed too: chain advanced and also failed
    assert local.calls == 2  # exactly one retry, no more
    assert "transient_retry" in error.reason


def test_no_transient_retry_for_state_change(tmp_path):
    local = SeqStrategy("a", "pierrondi", V2, [
        failed_outcome("pierrondi", "v2_image_failed: TimeoutError: boom"),
        solved_outcome("pierrondi"),
    ])
    strategies = {
        "pierrondi": [local],
        "capsolver": [FakeStrategy("b", "capsolver", V2, solved_outcome("capsolver"))],
    }
    chain = make_chain(tmp_path, strategies=strategies)
    chain.config.chain = lambda: ["pierrondi", "capsolver"]
    request = SolveRequest(
        type=ChallengeType.recaptcha_v2, sitekey="6Lc_test",
        page_url="https://example.com/form", purpose=SolvePurpose.state_change,
    )
    result, _ = chain.solve(request)
    assert result.provider == "capsolver"
    assert local.calls == 1  # state_change is never implicitly retried


def test_no_retry_for_commercial_provider(tmp_path):
    paid = SeqStrategy("b", "capsolver", V2, [
        failed_outcome("capsolver", "capsolver_failed: TimeoutError: boom"),
        solved_outcome("capsolver"),
    ])
    strategies = {
        "capsolver": [paid],
        "2captcha": [FakeStrategy("c", "2captcha", V2, solved_outcome("2captcha"))],
    }
    chain = make_chain(tmp_path, strategies=strategies)
    chain.config.chain = lambda: ["capsolver", "2captcha"]
    result, _ = chain.solve(req())
    assert result.provider == "2captcha"
    assert paid.calls == 1  # commercial providers are not retried


def test_no_retry_for_non_transient_local_failure(tmp_path):
    local = SeqStrategy("a", "pierrondi", V2, [
        failed_outcome("pierrondi", "wrong_tiles"),
        solved_outcome("pierrondi"),
    ])
    strategies = {
        "pierrondi": [local],
        "capsolver": [FakeStrategy("b", "capsolver", V2, solved_outcome("capsolver"))],
    }
    chain = make_chain(tmp_path, strategies=strategies)
    chain.config.chain = lambda: ["pierrondi", "capsolver"]
    result, _ = chain.solve(req())
    assert result.provider == "capsolver"
    assert local.calls == 1  # non-transient reasons are not retried
