"""Client lib + CLI: the canonical way ANY local process (MCP, skill, script,
n8n, browser adapter) talks to pierrondi-solver.

Usage (lib):
    from pierrondi_solver.client import detect_challenge, solve
    ch = detect_challenge(html, page_url)
    if ch:
        result = solve(ch)   # -> SolveResult or None

Usage (CLI):
    pierrondi-solve detect --html-file page.html --url https://example.com
    pierrondi-solve solve --type recaptcha_v2 --sitekey 6Lc... --url https://example.com
    pierrondi-solve health
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass

import httpx

DEFAULT_URL = "http://127.0.0.1:8791"

_SITEKEY_PATTERNS = {
    "recaptcha_v2": [
        re.compile(r'data-sitekey=["\']([A-Za-z0-9_-]{20,})["\']'),
        re.compile(r"grecaptcha\.execute\(['\"]([A-Za-z0-9_-]{20,})['\"]"),
    ],
    "hcaptcha": [
        re.compile(r'class=["\'][^"\']*h-captcha[^"\']*["\'][^>]*data-sitekey=["\']([A-Za-z0-9_-]{20,})["\']'),
        re.compile(r'data-sitekey=["\']([0-9a-f-]{36})["\']'),
    ],
    "turnstile": [
        re.compile(r'class=["\'][^"\']*cf-turnstile[^"\']*["\'][^>]*data-sitekey=["\']([A-Za-z0-9_-]{20,})["\']'),
    ],
    "cloudflare": [],  # interstitial has no sitekey; marker-based detection below
}

# Cloudflare interstitial / IUAM markers (no sitekey; solve = cf_clearance cookie)
_CF_INTERSTITIAL_MARKERS = [
    "just a moment",
    "cf_chl_",
    "cf-chl-",
    "cf-browser-verification",
    "checking your browser",
    "checking if the site connection is secure",
    "attention required! | cloudflare",
    "_cf_chl_opt",
    "challenge-platform",
]

_SCRIPT_MARKERS = {
    "recaptcha_v2": ["google.com/recaptcha/api.js", "grecaptcha"],
    "hcaptcha": ["hcaptcha.com/1/api.js", "hcaptcha"],
    "turnstile": ["challenges.cloudflare.com/turnstile", "cf-turnstile"],
}


@dataclass
class Challenge:
    type: str
    sitekey: str
    page_url: str


def detect_challenge(html: str, page_url: str) -> Challenge | None:
    """Extract (type, sitekey) from page HTML. Returns None when no known
    challenge marker is present. Cloudflare interstitial is checked first
    (it often embeds a Turnstile-like widget but must be solved as clearance)."""
    lowered = html.lower()
    if any(marker in lowered for marker in _CF_INTERSTITIAL_MARKERS):
        return Challenge(type="cloudflare", sitekey="", page_url=page_url)
    for ch_type in ("turnstile", "hcaptcha", "recaptcha_v2"):
        for pattern in _SITEKEY_PATTERNS[ch_type]:
            match = pattern.search(html)
            if match:
                return Challenge(type=ch_type, sitekey=match.group(1), page_url=page_url)
    for ch_type, markers in _SCRIPT_MARKERS.items():
        if any(m in html for m in markers):
            return Challenge(type=ch_type, sitekey="", page_url=page_url)
    return None


def solver_url() -> str:
    return os.environ.get("PIERRONDI_SOLVER_URL", DEFAULT_URL).rstrip("/")


def health(timeout: float = 5.0) -> dict:
    resp = httpx.get(f"{solver_url()}/health", timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _solve_payload(
    challenge: Challenge,
    lane: str,
    timeout_s: int,
    purpose: str,
    operation_id: str,
    attempt: int,
) -> dict:
    return {
        "type": challenge.type,
        "sitekey": challenge.sitekey or "unknown",
        "page_url": challenge.page_url,
        "lane": lane,
        "timeout_s": timeout_s,
        "purpose": purpose,
        "operation_id": operation_id,
        "attempt": attempt,
    }


def solve(
    challenge: Challenge,
    lane: str = "default",
    timeout_s: int = 120,
    purpose: str = "generic",
    operation_id: str = "",
    attempt: int = 1,
) -> dict | None:
    """POST /solve. Returns the result dict on success, None on unsolved
    (reason available via solve_verbose). Raises on transport errors so the
    caller can decide its own fallback."""
    resp = httpx.post(
        f"{solver_url()}/solve",
        json=_solve_payload(
            challenge, lane, timeout_s, purpose, operation_id, attempt
        ),
        timeout=timeout_s + 30,
    )
    if resp.status_code == 200:
        return resp.json()
    return None


def solve_verbose(
    challenge: Challenge,
    lane: str = "default",
    timeout_s: int = 120,
    purpose: str = "generic",
    operation_id: str = "",
    attempt: int = 1,
) -> dict:
    """Like solve(), but always returns a dict with 'solved' and 'reason'."""
    resp = httpx.post(
        f"{solver_url()}/solve",
        json=_solve_payload(
            challenge, lane, timeout_s, purpose, operation_id, attempt
        ),
        timeout=timeout_s + 30,
    )
    body = resp.json()
    if resp.status_code == 200:
        return {"solved": True, **body}
    return {"solved": False, **body}


def _cmd_detect(args: argparse.Namespace) -> int:
    html = sys.stdin.read() if args.html_file == "-" else open(args.html_file).read()
    challenge = detect_challenge(html, args.url)
    if challenge is None:
        print(json.dumps({"challenge": None}))
        return 1
    print(json.dumps({"challenge": challenge.__dict__}))
    return 0


def _cmd_solve(args: argparse.Namespace) -> int:
    challenge = Challenge(type=args.type, sitekey=args.sitekey, page_url=args.url)
    result = solve_verbose(
        challenge,
        lane=args.lane,
        timeout_s=args.timeout,
        purpose=args.purpose,
        operation_id=args.operation_id,
        attempt=args.attempt,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("solved") else 2


def _cmd_health(_args: argparse.Namespace) -> int:
    try:
        print(json.dumps(health(), indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "down", "error": str(exc)}))
        return 1


def _check(name: str, ok: bool, detail: str = "") -> dict:
    return {"check": name, "ok": ok, "detail": detail}


def doctor() -> list[dict]:
    """Audit the whole solver stack. Returns a list of check results."""
    results = []

    # 1. env var
    env_url = os.environ.get("PIERRONDI_SOLVER_URL", "")
    results.append(_check("env_var", bool(env_url),
                          env_url or f"PIERRONDI_SOLVER_URL not set (default {DEFAULT_URL} applies)"))

    # 2. service health
    try:
        body = health(timeout=5)
        results.append(_check("service_health", body.get("status") == "ok",
                              ",".join(body.get("providers", []))))
    except Exception as exc:
        results.append(_check("service_health", False, str(exc)[:200]))

    # 3. LaunchAgent state (macOS)
    try:
        import subprocess
        out = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/com.paulo.pierrondi-solver"],
            capture_output=True, text=True, timeout=10).stdout
        running = "state = running" in out
        results.append(_check("launchagent", running,
                              "running" if running else "loaded but not running"))
    except Exception as exc:
        results.append(_check("launchagent", False, str(exc)[:120]))

    # 4. local-solve deps
    try:
        import playwright  # noqa: F401
        results.append(_check("dep_playwright", True))
    except ImportError:
        results.append(_check("dep_playwright", False, "pip install -e '.[local-solve]'"))
    try:
        import faster_whisper  # noqa: F401
        results.append(_check("dep_faster_whisper", True))
    except ImportError:
        results.append(_check("dep_faster_whisper", False, "pip install -e '.[local-solve]'"))

    # 5. chromium binary
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            browser.close()
        results.append(_check("chromium_binary", True))
    except Exception as exc:
        results.append(_check("chromium_binary", False, str(exc)[:120]))

    # 6. commercial keys (presence only, never values)
    for env_name in ("CAPSOLVER_API_KEY", "TWOCAPTCHA_API_KEY", "CAPMONSTER_API_KEY"):
        results.append(_check(f"key_{env_name.lower()}", bool(os.environ.get(env_name)),
                              "set" if os.environ.get(env_name) else "not set (fallback indisponível)"))
    results.append(_check("proxy_capsolver", bool(os.environ.get("CAPSOLVER_PROXY")),
                          "set" if os.environ.get("CAPSOLVER_PROXY") else "not set (AntiCloudflareTask off)"))
    return results


def _cmd_doctor(_args: argparse.Namespace) -> int:
    results = doctor()
    ok = all(r["ok"] for r in results if not r["check"].startswith("key_")
             and r["check"] != "proxy_capsolver")
    print(json.dumps({"status": "ok" if ok else "degraded", "checks": results}, indent=2))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pierrondi-solve")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_detect = sub.add_parser("detect", help="detect challenge in HTML")
    p_detect.add_argument("--html-file", default="-", help="path or '-' for stdin")
    p_detect.add_argument("--url", required=True)
    p_detect.set_defaults(func=_cmd_detect)

    p_solve = sub.add_parser("solve", help="solve a challenge via the service")
    p_solve.add_argument("--type", required=True,
                         choices=["recaptcha_v2", "recaptcha_v3", "hcaptcha", "turnstile",
                                  "cloudflare"])
    p_solve.add_argument("--sitekey", required=True)
    p_solve.add_argument("--url", required=True)
    p_solve.add_argument("--lane", default="default")
    p_solve.add_argument("--timeout", type=int, default=120)
    p_solve.add_argument(
        "--purpose",
        choices=["generic", "authentication", "read_only", "state_change"],
        default="generic",
    )
    p_solve.add_argument(
        "--operation-id",
        default="",
        help="opaque non-secret correlation ID (never stored raw in telemetry)",
    )
    p_solve.add_argument("--attempt", type=int, default=1)
    p_solve.set_defaults(func=_cmd_solve)

    p_health = sub.add_parser("health", help="service health check")
    p_health.set_defaults(func=_cmd_health)

    p_doctor = sub.add_parser("doctor", help="audit the whole solver stack")
    p_doctor.set_defaults(func=_cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
