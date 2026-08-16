"""Tests for the pierrondi-solver MCP server.

The server delegates to ``pierrondi_solver.client`` (which talks to the HTTP
service). To keep these tests CI-safe (no running service, no network) we call
the tool functions directly with the client module monkeypatched, and we assert
the MCP server exposes the expected tools.
"""
from __future__ import annotations

import pierrondi_solver.mcp_server as mcp_server
from pierrondi_solver.mcp_server import (
    detect_challenge,
    get_browser_session,
    service_doctor,
    service_health,
    solve_challenge,
)


# --- server registration ------------------------------------------------

def test_mcp_server_name():
    assert mcp_server.mcp.name == "pierrondi-solver"


def test_mcp_server_exposes_expected_tools():
    # FastMCP stores registered tools in ._tool_manager._tools (private but stable).
    tools = mcp_server.mcp._tool_manager._tools
    expected = {
        "solve_challenge",
        "detect_challenge",
        "get_browser_session",
        "service_health",
        "service_doctor",
    }
    assert expected.issubset(set(tools.keys())), (
        f"missing tools: {expected - set(tools.keys())}"
    )


# --- solve_challenge (client mocked) ------------------------------------

def test_solve_challenge_success(monkeypatch):
    captured = {}

    def fake_solve_verbose(challenge, **kwargs):
        captured["challenge"] = challenge
        captured.update(kwargs)
        return {
            "solved": True,
            "token": "TOKEN_ABC",
            "strategy": "v2_audio",
            "provider": "pierrondi",
        }

    monkeypatch.setattr(mcp_server.client, "solve_verbose", fake_solve_verbose)
    result = solve_challenge(
        challenge_type="recaptcha_v2",
        sitekey="SITEKEY123",
        page_url="https://example.com/page",
    )
    assert result["solved"] is True
    assert result["token"] == "TOKEN_ABC"
    assert captured["challenge"].type == "recaptcha_v2"
    assert captured["challenge"].sitekey == "SITEKEY123"
    assert captured["challenge"].page_url == "https://example.com/page"
    assert captured["lane"] == "default"
    assert captured["purpose"] == "generic"


def test_solve_challenge_unsolved(monkeypatch):
    monkeypatch.setattr(
        mcp_server.client,
        "solve_verbose",
        lambda c, **kwargs: {
            "solved": False,
            "error": "unsolved",
            "reason": "all providers failed",
        },
    )
    result = solve_challenge(
        challenge_type="cloudflare",
        page_url="https://example.com/protected",
    )
    assert result["solved"] is False
    assert result["reason"] == "all providers failed"


def test_solve_challenge_cloudflare_passes_empty_sitekey(monkeypatch):
    captured = {}

    def fake(challenge, **kwargs):
        captured["challenge"] = challenge
        return {"solved": True}

    monkeypatch.setattr(mcp_server.client, "solve_verbose", fake)
    solve_challenge(challenge_type="cloudflare", page_url="https://x.example")
    assert captured["challenge"].sitekey == ""
    assert captured["challenge"].type == "cloudflare"


def test_solve_challenge_passes_workflow_context(monkeypatch):
    captured = {}

    def fake(challenge, **kwargs):
        captured.update(kwargs)
        return {"solved": True}

    monkeypatch.setattr(mcp_server.client, "solve_verbose", fake)
    solve_challenge(
        challenge_type="recaptcha_v2",
        sitekey="SITEKEY123",
        page_url="https://example.com/page",
        purpose="read_only",
        operation_id="check-7",
        attempt=4,
    )
    assert captured["purpose"] == "read_only"
    assert captured["operation_id"] == "check-7"
    assert captured["attempt"] == 4


# --- detect_challenge ---------------------------------------------------

def test_detect_challenge_found(monkeypatch):
    from pierrondi_solver.client import Challenge

    monkeypatch.setattr(
        mcp_server.client,
        "detect_challenge",
        lambda html, page_url: Challenge(
            type="recaptcha_v2", sitekey="SK1", page_url=page_url
        ),
    )
    result = detect_challenge(html="<html>...</html>", page_url="https://x.example")
    assert result["challenge"]["type"] == "recaptcha_v2"
    assert result["challenge"]["sitekey"] == "SK1"


def test_detect_challenge_none(monkeypatch):
    monkeypatch.setattr(mcp_server.client, "detect_challenge", lambda html, page_url: None)
    result = detect_challenge(html="<html>no challenge</html>", page_url="https://x.example")
    assert result == {"challenge": None}


# --- get_browser_session ------------------------------------------------

def test_get_browser_session_specific_engine_available(monkeypatch):
    monkeypatch.setattr(mcp_server, "browser_deps_missing", lambda name: [])
    result = get_browser_session(engine="chromium")
    assert result["engine"] == "chromium"
    assert result["available"] is True
    assert result["deps_missing"] == []


def test_get_browser_session_specific_engine_missing(monkeypatch):
    monkeypatch.setattr(
        mcp_server, "browser_deps_missing", lambda name: ["install-hint"]
    )
    result = get_browser_session(engine="nodriver")
    assert result["engine"] == "nodriver"
    assert result["available"] is False
    assert result["deps_missing"] == ["install-hint"]


def test_get_browser_session_list_all(monkeypatch):
    monkeypatch.setattr(mcp_server, "browser_deps_missing", lambda name: [])
    result = get_browser_session(engine="")
    assert "engines" in result
    names = [e["name"] for e in result["engines"]]
    assert "chromium" in names
    assert "firefox" in names
    assert "nodriver" in names
    assert all(e["available"] is True for e in result["engines"])


# --- service_health -----------------------------------------------------

def test_service_health(monkeypatch):
    monkeypatch.setattr(
        mcp_server.client,
        "health",
        lambda timeout=5.0: {"status": "ok", "providers": ["pierrondi", "capsolver"]},
    )
    result = service_health()
    assert result["status"] == "ok"
    assert "pierrondi" in result["providers"]


# --- service_doctor -----------------------------------------------------

def test_service_doctor_ok(monkeypatch):
    monkeypatch.setattr(
        mcp_server.client,
        "doctor",
        lambda: [
            {"check": "env_var", "ok": True, "detail": "set"},
            {"check": "service_health", "ok": True, "detail": "ok"},
        ],
    )
    result = service_doctor()
    assert result["status"] == "ok"
    assert len(result["checks"]) == 2


def test_service_doctor_degraded(monkeypatch):
    monkeypatch.setattr(
        mcp_server.client,
        "doctor",
        lambda: [
            {"check": "env_var", "ok": True, "detail": "set"},
            {"check": "service_health", "ok": False, "detail": "connection refused"},
            {"check": "key_capsolver_api_key", "ok": False, "detail": "not set"},
        ],
    )
    result = service_doctor()
    # key_* checks don't count toward degraded status
    assert result["status"] == "degraded"
    assert any(c["check"] == "service_health" and c["ok"] is False for c in result["checks"])
