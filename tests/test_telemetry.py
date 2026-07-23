from pierrondi_solver.telemetry import Telemetry, token_fingerprint


def make_telemetry(tmp_path):
    return Telemetry(str(tmp_path / "telemetry.db"))


def test_log_and_summary(tmp_path):
    tel = make_telemetry(tmp_path)
    tel.log_attempt("pierrondi", "recaptcha_v2", "v2_audio", "https://x.com/p", "B",
                    8300, 0.0, True, token="SECRET-TOKEN-123")
    tel.log_attempt("capsolver", "recaptcha_v2", "task_api", "https://x.com/p", "B",
                    15000, 0.0015, False, reason="timeout")
    summary = tel.summary()
    assert summary["attempts"] == 2
    assert summary["solved"] == 1
    assert summary["by_provider"]["pierrondi"]["success_rate"] == 1.0
    assert summary["by_provider"]["capsolver"]["cost_usd"] == 0.0015


def test_token_never_stored_raw(tmp_path):
    tel = make_telemetry(tmp_path)
    tel.log_attempt("pierrondi", "recaptcha_v2", "v2_audio", "https://x.com", "B",
                    100, 0.0, True, token="SECRET-TOKEN-123")
    import sqlite3
    with sqlite3.connect(str(tmp_path / "telemetry.db")) as conn:
        row = conn.execute("SELECT token_hash FROM solves").fetchone()
    assert row[0] == token_fingerprint("SECRET-TOKEN-123")
    assert "SECRET-TOKEN-123" not in row[0]


def test_site_host_extracted(tmp_path):
    tel = make_telemetry(tmp_path)
    tel.log_attempt("pierrondi", "recaptcha_v2", "v2_audio",
                    "https://example.com/some/path?q=1", "B", 100, 0.0, True)
    import sqlite3
    with sqlite3.connect(str(tmp_path / "telemetry.db")) as conn:
        host = conn.execute("SELECT site_host FROM solves").fetchone()[0]
    assert host == "example.com"


def test_summary_window_filters_old(tmp_path):
    import sqlite3, time
    tel = make_telemetry(tmp_path)
    tel.log_attempt("pierrondi", "recaptcha_v2", "v2_audio", "https://x.com", "B",
                    100, 0.0, True)
    with sqlite3.connect(str(tmp_path / "telemetry.db")) as conn:
        conn.execute("UPDATE solves SET ts = ?", (time.time() - 90000,))
    assert tel.summary(since_s=3600)["attempts"] == 0
