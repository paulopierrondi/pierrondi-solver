import json

import httpx
import pytest

from pierrondi_solver.client import (
    Challenge,
    detect_challenge,
    main,
    solve,
    solve_verbose,
)

RECAPTCHA_HTML = '''
<html><head><script src="https://www.google.com/recaptcha/api.js"></script></head>
<body><div class="g-recaptcha" data-sitekey="6Lc1234567890abcdefABCDEF123456"></div></body></html>
'''
TURNSTILE_HTML = '''
<div class="cf-turnstile" data-sitekey="0x4AAAAAA1234567890abcdef"></div>
'''
HCAPTCHA_HTML = '''
<div class="h-captcha" data-sitekey="10000000-ffff-ffff-ffff-000000000001"></div>
'''
CLEAN_HTML = "<html><body><p>no challenge here</p></body></html>"
EXECUTE_HTML = '''
<script>grecaptcha.execute('6LcExecuteKey1234567890abcd', {action: 'submit'});</script>
'''
CF_INTERSTITIAL_HTML = '''
<html><head><title>Just a moment...</title></head>
<body><div id="cf-chl-widget"></div>
<script>window._cf_chl_opt = {cvId: '3'};</script>
<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script></body></html>
'''


def test_detect_recaptcha_sitekey():
    ch = detect_challenge(RECAPTCHA_HTML, "https://example.com")
    assert ch.type == "recaptcha_v2"
    assert ch.sitekey == "6Lc1234567890abcdefABCDEF123456"


def test_detect_turnstile_wins_over_recaptcha_marker():
    ch = detect_challenge(TURNSTILE_HTML + RECAPTCHA_HTML, "https://example.com")
    assert ch.type == "turnstile"
    assert ch.sitekey == "0x4AAAAAA1234567890abcdef"


def test_detect_hcaptcha():
    ch = detect_challenge(HCAPTCHA_HTML, "https://example.com")
    assert ch.type == "hcaptcha"


def test_detect_execute_call():
    ch = detect_challenge(EXECUTE_HTML, "https://example.com")
    assert ch.type == "recaptcha_v2"
    assert ch.sitekey == "6LcExecuteKey1234567890abcd"


def test_detect_clean_page_returns_none():
    assert detect_challenge(CLEAN_HTML, "https://example.com") is None


def test_detect_cloudflare_interstitial():
    ch = detect_challenge(CF_INTERSTITIAL_HTML, "https://example.com/protected")
    assert ch.type == "cloudflare"
    assert ch.sitekey == ""


def test_cloudflare_interstitial_wins_over_turnstile_widget():
    # Interstitial pages embed challenge-platform scripts; must classify as
    # cloudflare (clearance flow), not as a turnstile token solve.
    ch = detect_challenge(CF_INTERSTITIAL_HTML + TURNSTILE_HTML, "https://example.com")
    assert ch.type == "cloudflare"


class FakeTransport(httpx.BaseTransport):
    def __init__(self, status_code, body):
        self._status = status_code
        self._body = body
        self.last_request = None

    def handle_request(self, request):
        self.last_request = request
        return httpx.Response(self._status, json=self._body)


def mock_client(monkeypatch, status_code, body):
    fake = FakeTransport(status_code, body)
    transport = httpx.MockTransport(fake.handle_request)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: httpx.Client(transport=transport).post(*a, **kw))
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Client(transport=transport).get(*a, **kw))
    return fake


def test_solve_success(monkeypatch):
    mock_client(monkeypatch, 200, {"token": "TOK", "strategy": "v2_audio",
                                   "provider": "pierrondi", "latency_ms": 10, "cost_usd": 0.0})
    result = solve(Challenge("recaptcha_v2", "6Lc", "https://example.com"))
    assert result["token"] == "TOK"


def test_solve_sends_workflow_context(monkeypatch):
    fake = mock_client(
        monkeypatch,
        200,
        {"token": "TOK", "strategy": "v2_audio", "provider": "pierrondi",
         "latency_ms": 10, "cost_usd": 0.0},
    )
    solve(
        Challenge("recaptcha_v2", "6Lc", "https://example.com"),
        purpose="read_only",
        operation_id="availability-42",
        attempt=3,
    )
    payload = json.loads(fake.last_request.content)
    assert payload["purpose"] == "read_only"
    assert payload["operation_id"] == "availability-42"
    assert payload["attempt"] == 3


def test_solve_unsolved_returns_none(monkeypatch):
    mock_client(monkeypatch, 422, {"error": "unsolved", "reason": "boom"})
    assert solve(Challenge("recaptcha_v2", "6Lc", "https://example.com")) is None


def test_solve_verbose_always_dict(monkeypatch):
    mock_client(monkeypatch, 422, {"error": "unsolved", "reason": "boom"})
    result = solve_verbose(Challenge("recaptcha_v2", "6Lc", "https://example.com"))
    assert result["solved"] is False
    assert result["reason"] == "boom"


def test_cli_detect(capsys, tmp_path):
    html_file = tmp_path / "page.html"
    html_file.write_text(RECAPTCHA_HTML)
    rc = main(["detect", "--html-file", str(html_file), "--url", "https://example.com"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["challenge"]["type"] == "recaptcha_v2"


def test_cli_detect_clean(capsys, tmp_path):
    html_file = tmp_path / "page.html"
    html_file.write_text(CLEAN_HTML)
    rc = main(["detect", "--html-file", str(html_file), "--url", "https://example.com"])
    assert rc == 1
    assert json.loads(capsys.readouterr().out)["challenge"] is None


def test_cli_health_down(capsys, monkeypatch):
    def boom(*a, **kw):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(httpx, "get", boom)
    rc = main(["health"])
    assert rc == 1
    assert json.loads(capsys.readouterr().out)["status"] == "down"


def test_cli_solve_accepts_workflow_context(capsys, monkeypatch):
    captured = {}

    def fake_solve_verbose(challenge, **kwargs):
        captured.update(kwargs)
        return {"solved": True, "token": "TOK"}

    monkeypatch.setattr("pierrondi_solver.client.solve_verbose", fake_solve_verbose)
    rc = main([
        "solve",
        "--type", "recaptcha_v2",
        "--sitekey", "6Lc",
        "--url", "https://example.com",
        "--purpose", "state_change",
        "--operation-id", "booking-42",
        "--attempt", "2",
    ])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["solved"] is True
    assert captured["purpose"] == "state_change"
    assert captured["operation_id"] == "booking-42"
    assert captured["attempt"] == 2
