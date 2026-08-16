import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

HOOK_PATH = Path(__file__).parent.parent / "hooks" / "captcha_posttool_hook.py"
spec = importlib.util.spec_from_file_location("captcha_posttool_hook", HOOK_PATH)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


def run_hook(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    out = io.StringIO()
    with redirect_stdout(out):
        rc = hook.main()
    return rc, out.getvalue()


def payload_with(text):
    return {"tool_name": "mcp__scrapling__fetch", "tool_input": {}, "tool_response": text}


def test_silent_on_clean_response(monkeypatch):
    rc, out = run_hook(monkeypatch, payload_with("<html><body>normal page</body></html>"))
    assert rc == 0
    assert out == ""


def test_fires_on_recaptcha(monkeypatch):
    html = '<div class="g-recaptcha" data-sitekey="6LcABCDEF1234567890abcdef12345"></div>'
    rc, out = run_hook(monkeypatch, payload_with(html))
    assert rc == 0
    body = json.loads(out)
    ctx = body["hookSpecificOutput"]["additionalContext"]
    assert "pierrondi-solver" in ctx
    assert "sitekey=6LcABCDEF1234567890abcdef12345" in ctx
    assert body["hookSpecificOutput"]["hookEventName"] == "PostToolUse"


def test_fires_on_cloudflare_marker(monkeypatch):
    rc, out = run_hook(monkeypatch, payload_with("verify you are human - challenges.cloudflare.com"))
    assert rc == 0
    assert json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_fires_on_turnstile(monkeypatch):
    rc, out = run_hook(monkeypatch, payload_with('<div class="cf-turnstile" data-sitekey="0x4AAAAAA1234567890abcdef"></div>'))
    assert rc == 0
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "sitekey=0x4AAAAAA1234567890abcdef" in ctx


def test_silent_on_malformed_stdin(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("not-json{{{"))
    out = io.StringIO()
    with redirect_stdout(out):
        rc = hook.main()
    assert rc == 0
    assert out.getvalue() == ""


def test_handles_dict_response(monkeypatch):
    payload = {"tool_name": "WebFetch", "tool_input": {},
               "tool_response": {"content": "hcaptcha.com/1/api.js loaded"}}
    rc, out = run_hook(monkeypatch, payload)
    assert rc == 0
    assert "pierrondi-solver" in json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_kimi_surface_prints_plain_text(monkeypatch):
    payload = {"client_type": "kimi_code_cli", "tool_name": "FetchURL",
               "tool_response": "Just a moment... cf_chl_ challenge-platform"}
    rc, out = run_hook(monkeypatch, payload)
    assert rc == 0
    assert "pierrondi-solver" in out
    assert not out.strip().startswith("{")  # plain text, not Claude JSON


def test_kimi_tool_result_fallback(monkeypatch):
    payload = {"client_type": "kimi_code_cli",
               "tool_result": {"html": '<div class="cf-turnstile" data-sitekey="0x4AAAAAA1234567890abcdef"></div>'}}
    rc, out = run_hook(monkeypatch, payload)
    assert rc == 0
    assert "sitekey=0x4AAAAAA1234567890abcdef" in out
