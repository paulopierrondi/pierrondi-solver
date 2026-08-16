from pierrondi_solver.telemetry import (
    Telemetry,
    operation_fingerprint,
    token_fingerprint,
)


def make_telemetry(tmp_path):
    return Telemetry(str(tmp_path / "telemetry.db"))


def test_log_and_summary(tmp_path):
    tel = make_telemetry(tmp_path)
    tel.log_attempt("pierrondi", "recaptcha_v2", "v2_audio", "https://x.com/p", "B",
                    8300, 0.0, True, token="SECRET-TOKEN-123",
                    purpose="read_only", operation_id="check-42")
    tel.log_attempt("capsolver", "recaptcha_v2", "task_api", "https://x.com/p", "B",
                    15000, 0.0015, False, reason="timeout")
    summary = tel.summary()
    assert summary["attempts"] == 2
    assert summary["solved"] == 1
    assert summary["by_provider"]["pierrondi"]["success_rate"] == 1.0
    assert summary["by_provider"]["capsolver"]["cost_usd"] == 0.0015
    assert summary["by_purpose"]["read_only"]["attempts"] == 1
    assert summary["by_purpose"]["generic"]["attempts"] == 1


def test_token_never_stored_raw(tmp_path):
    tel = make_telemetry(tmp_path)
    tel.log_attempt("pierrondi", "recaptcha_v2", "v2_audio", "https://x.com", "B",
                    100, 0.0, True, token="SECRET-TOKEN-123")
    import sqlite3
    with sqlite3.connect(str(tmp_path / "telemetry.db")) as conn:
        row = conn.execute("SELECT token_hash FROM solves").fetchone()
    assert row[0] == token_fingerprint("SECRET-TOKEN-123")
    assert "SECRET-TOKEN-123" not in row[0]


def test_operation_id_never_stored_raw(tmp_path):
    tel = make_telemetry(tmp_path)
    tel.log_attempt(
        "pierrondi", "recaptcha_v2", "v2_audio", "https://x.com", "B",
        100, 0.0, True, operation_id="workflow-sensitive-label",
    )
    import sqlite3
    with sqlite3.connect(str(tmp_path / "telemetry.db")) as conn:
        row = conn.execute("SELECT operation_hash FROM solves").fetchone()
    assert row[0] == operation_fingerprint("workflow-sensitive-label")
    assert "workflow-sensitive-label" not in row[0]


def test_existing_database_is_migrated(tmp_path):
    import sqlite3

    db_path = str(tmp_path / "legacy.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE solves ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,"
            "provider TEXT NOT NULL, challenge_type TEXT NOT NULL,"
            "strategy TEXT NOT NULL, site_host TEXT NOT NULL, lane TEXT NOT NULL,"
            "latency_ms INTEGER NOT NULL, cost_usd REAL NOT NULL,"
            "success INTEGER NOT NULL, token_hash TEXT NOT NULL DEFAULT '',"
            "reason TEXT NOT NULL DEFAULT '')"
        )
    Telemetry(db_path)
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(solves)")}
    assert {"purpose", "operation_hash"}.issubset(columns)


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
