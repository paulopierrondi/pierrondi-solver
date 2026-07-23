"""SQLite telemetry: every solve attempt is logged (token truncated to hash prefix)."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from urllib.parse import urlparse

_SCHEMA = """
CREATE TABLE IF NOT EXISTS solves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    provider TEXT NOT NULL,
    challenge_type TEXT NOT NULL,
    strategy TEXT NOT NULL,
    site_host TEXT NOT NULL,
    lane TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    success INTEGER NOT NULL,
    token_hash TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_solves_ts ON solves(ts);
CREATE INDEX IF NOT EXISTS idx_solves_provider ON solves(provider, ts);
"""


def _site_host(page_url: str) -> str:
    try:
        return urlparse(page_url).netloc or page_url[:64]
    except Exception:
        return page_url[:64]


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:12] if token else ""


class Telemetry:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def log_attempt(
        self,
        provider: str,
        challenge_type: str,
        strategy: str,
        page_url: str,
        lane: str,
        latency_ms: int,
        cost_usd: float,
        success: bool,
        token: str = "",
        reason: str = "",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO solves (ts, provider, challenge_type, strategy, site_host, lane,"
                " latency_ms, cost_usd, success, token_hash, reason) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    time.time(),
                    provider,
                    challenge_type,
                    strategy,
                    _site_host(page_url),
                    lane,
                    int(latency_ms),
                    float(cost_usd),
                    1 if success else 0,
                    token_fingerprint(token),
                    reason[:500],
                ),
            )

    def summary(self, since_s: float = 86400) -> dict:
        cutoff = time.time() - since_s
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT provider, COUNT(*), SUM(success), ROUND(SUM(cost_usd), 6),"
                " ROUND(AVG(latency_ms)) FROM solves WHERE ts >= ? GROUP BY provider",
                (cutoff,),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*), SUM(success) FROM solves WHERE ts >= ?", (cutoff,)
            ).fetchone()
        providers = {
            r[0]: {
                "attempts": r[1],
                "solved": r[2] or 0,
                "cost_usd": r[3] or 0.0,
                "avg_latency_ms": int(r[4] or 0),
                "success_rate": round((r[2] or 0) / r[1], 4) if r[1] else 0.0,
            }
            for r in rows
        }
        return {
            "window_s": since_s,
            "attempts": total[0] or 0,
            "solved": total[1] or 0,
            "by_provider": providers,
        }
