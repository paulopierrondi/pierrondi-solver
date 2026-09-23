import json
import os

import pytest

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


@pytest.mark.skipif(hasattr(os, "getuid"), reason="windows persistence path")
def test_doctor_windows_startup_entry_detected(tmp_path, monkeypatch):
    startup = tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    (startup / "pierrondi-solver-start.cmd").touch()

    check = next(r for r in doctor() if r["check"] == "launchagent")
    assert check["ok"] is True
    assert "startup entry present" in check["detail"]


@pytest.mark.skipif(hasattr(os, "getuid"), reason="windows persistence path")
def test_doctor_windows_startup_entry_missing(tmp_path, monkeypatch):
    startup = tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    check = next(r for r in doctor() if r["check"] == "launchagent")
    assert check["ok"] is False
    assert "no Startup entry" in check["detail"]
