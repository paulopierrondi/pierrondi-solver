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


def test_stats():
    breaker, _ = make_breaker()
    breaker.record("capsolver", success=True)
    breaker.record("capsolver", success=False)
    stats = breaker.stats("capsolver")
    assert stats["samples"] == 2
    assert stats["failures"] == 1
    assert stats["failure_rate"] == 0.5
    assert stats["available"] is True
