import pytest

from pierrondi_solver.circuit_breaker import CircuitBreaker


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_breaker(**kw):
    clock = kw.pop("clock", FakeClock())
    return CircuitBreaker(failure_rate=0.30, min_samples=5, window_s=3600, clock=clock), clock


def test_available_below_min_samples():
    breaker, _ = make_breaker()
    for _ in range(4):
        breaker.record("capsolver", success=False)
    assert breaker.is_available("capsolver")


def test_opens_above_failure_rate():
    breaker, _ = make_breaker()
    for ok in [False, False, True, False, True]:
        breaker.record("capsolver", success=ok)  # 3/5 = 60% failure
    assert not breaker.is_available("capsolver")


def test_stays_closed_at_threshold():
    breaker, _ = make_breaker()
    for ok in [False, True, True, True, True]:
        breaker.record("capsolver", success=ok)  # 1/5 = 20% failure
    assert breaker.is_available("capsolver")


def test_window_prunes_old_failures():
    breaker, clock = make_breaker()
    for _ in range(5):
        breaker.record("capsolver", success=False)
    assert not breaker.is_available("capsolver")
    clock.now += 3601  # failures leave the window
    assert breaker.is_available("capsolver")


def test_providers_tracked_independently():
    breaker, _ = make_breaker()
    for _ in range(5):
        breaker.record("capsolver", success=False)
        breaker.record("2captcha", success=True)
    assert not breaker.is_available("capsolver")
    assert breaker.is_available("2captcha")


def test_invalid_params():
    with pytest.raises(ValueError):
        CircuitBreaker(failure_rate=0)
    with pytest.raises(ValueError):
        CircuitBreaker(min_samples=0)
    with pytest.raises(ValueError):
        CircuitBreaker(cooldown_s=-1)


def test_stats():
    breaker, _ = make_breaker()
    breaker.record("capsolver", success=True)
    breaker.record("capsolver", success=False)
    stats = breaker.stats("capsolver")
    assert stats["samples"] == 2
    assert stats["failures"] == 1
    assert stats["failure_rate"] == 0.5
    assert stats["available"] is True
    assert stats["half_open"] is False


# --- half-open probe ---


def _open_breaker(breaker):
    for _ in range(5):
        breaker.record("capsolver", success=False)


def test_half_open_trial_after_cooldown_closes_on_success():
    breaker, clock = make_breaker()
    _open_breaker(breaker)
    assert not breaker.is_available("capsolver")
    clock.now += 299  # cooldown (300s) not elapsed
    assert not breaker.is_available("capsolver")
    clock.now += 1
    assert breaker.is_available("capsolver")  # one trial attempt allowed
    assert not breaker.is_available("capsolver")  # probe already in flight
    breaker.record("capsolver", success=True)
    assert breaker.is_available("capsolver")  # closed again, fresh window
    stats = breaker.stats("capsolver")
    assert stats["samples"] == 0


def test_half_open_trial_failure_reopens_and_restarts_cooldown():
    breaker, clock = make_breaker()
    _open_breaker(breaker)
    assert not breaker.is_available("capsolver")  # marks the open timestamp
    clock.now += 300
    assert breaker.is_available("capsolver")  # trial armed
    breaker.record("capsolver", success=False)
    assert not breaker.is_available("capsolver")  # re-opened immediately
    clock.now += 299
    assert not breaker.is_available("capsolver")  # cooldown restarted
    clock.now += 1
    assert breaker.is_available("capsolver")  # new trial allowed


def test_stats_read_does_not_arm_probe():
    breaker, clock = make_breaker()
    _open_breaker(breaker)
    assert not breaker.is_available("capsolver")  # marks the open timestamp
    clock.now += 300
    assert breaker.stats("capsolver")["available"] is False
    assert breaker.stats("capsolver")["half_open"] is False
    assert breaker.is_available("capsolver")  # probe still available for solve


# --- telemetry seeding ---


def test_seed_breaker_opens_degraded_provider(tmp_path):
    from pierrondi_solver.chain import _seed_breaker
    from pierrondi_solver.config import Config
    from pierrondi_solver.telemetry import AttemptLog, Telemetry

    telemetry = Telemetry(str(tmp_path / "t.db"))
    for _ in range(5):
        telemetry.log_attempt(AttemptLog(
            provider="capsolver", challenge_type="recaptcha_v2", strategy="s",
            page_url="https://example.com", lane="default", latency_ms=1,
            cost_usd=0.0, success=False,
        ))
    breaker, _ = make_breaker()
    _seed_breaker(breaker, telemetry, Config())
    assert not breaker.is_available("capsolver")


def test_seed_breaker_keeps_healthy_provider_closed(tmp_path):
    from pierrondi_solver.chain import _seed_breaker
    from pierrondi_solver.config import Config
    from pierrondi_solver.telemetry import AttemptLog, Telemetry

    telemetry = Telemetry(str(tmp_path / "t.db"))
    for ok in [True, True, True, True, False]:
        telemetry.log_attempt(AttemptLog(
            provider="capsolver", challenge_type="recaptcha_v2", strategy="s",
            page_url="https://example.com", lane="default", latency_ms=1,
            cost_usd=0.0, success=ok,
        ))
    breaker, _ = make_breaker()
    _seed_breaker(breaker, telemetry, Config())
    assert breaker.is_available("capsolver")


def test_seed_breaker_degrades_safe_on_telemetry_error():
    from pierrondi_solver.chain import _seed_breaker
    from pierrondi_solver.config import Config

    class _BoomTelemetry:
        def provider_outcomes(self, window_s):
            raise RuntimeError("db unreadable")

    breaker, _ = make_breaker()
    _seed_breaker(breaker, _BoomTelemetry(), Config())
    assert breaker.is_available("capsolver")  # starts clean
