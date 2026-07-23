import json

from pierrondi_solver.client import doctor, main


def test_doctor_returns_structured_checks():
    results = doctor()
    names = {r["check"] for r in results}
    assert "env_var" in names
    assert "service_health" in names
    assert "dep_playwright" in names
    assert "dep_faster_whisper" in names
    assert "chromium_binary" in names
    for r in results:
        assert isinstance(r["ok"], bool)


def test_doctor_core_deps_present():
    results = {r["check"]: r["ok"] for r in doctor()}
    # deps are installed in this venv
    assert results["dep_playwright"] is True
    assert results["dep_faster_whisper"] is True
    assert results["chromium_binary"] is True


def test_doctor_cli_runs(capsys):
    rc = main(["doctor"])
    body = json.loads(capsys.readouterr().out)
    assert body["status"] in ("ok", "degraded")
    assert isinstance(body["checks"], list)
    assert rc in (0, 1)
