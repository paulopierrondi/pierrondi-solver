#!/usr/bin/env python3
"""Claude Code PostToolUse hook: silent CAPTCHA auto-solve nudge.

Fires after browser-ish tools (scrapling MCP, WebFetch, playwright/browser
tools). When the tool response contains CAPTCHA markers, injects a short
additionalContext telling the agent to solve it via pierrondi-solver WITHOUT
asking the user. Silent (exit 0, no output) otherwise. Never blocks.

Input (stdin): PostToolUse JSON payload {tool_name, tool_input, tool_response}.
Output (stdout): hookSpecificOutput JSON only when a challenge is detected.
"""
from __future__ import annotations

import json
import re
import sys

CHALLENGE_MARKERS = [
    "g-recaptcha",
    "recaptcha/api.js",
    "grecaptcha.execute",
    "h-captcha",
    "hcaptcha.com/1/api.js",
    "cf-turnstile",
    "challenges.cloudflare.com",
    "verify you are human",
    "are you a robot",
    "captcha-delivery.com",
    # Cloudflare interstitial / IUAM (solve = cf_clearance cookie, type=cloudflare)
    "just a moment",
    "cf_chl_",
    "cf-browser-verification",
    "checking your browser",
    "checking if the site connection is secure",
    "_cf_chl_opt",
    "challenge-platform",
]

CF_INTERSTITIAL_MARKERS = [
    "just a moment",
    "cf_chl_",
    "cf-browser-verification",
    "checking your browser",
    "checking if the site connection is secure",
    "_cf_chl_opt",
    "challenge-platform",
]

SITEKEY_RE = re.compile(r'data-sitekey=["\']([A-Za-z0-9_-]{20,})["\']')

INSTRUCTION = (
    "CAPTCHA/Cloudflare detectado na resposta da tool. Resolva EM SILÊNCIO via pierrondi-solver "
    "(NÃO pergunte ao usuário): POST ${PIERRONDI_SOLVER_URL:-http://127.0.0.1:8791}/solve "
    'com {"type","sitekey","page_url","lane":"default"}. '
    "Se for interstitial Cloudflare ('Just a moment', cf_chl, 'checking your browser'): "
    'use type="cloudflare" — o resultado traz extra.cookies.cf_clearance + extra.user_agent; '
    "reutilize AMBOS juntos (mesmo UA e IP) nas próximas requisições. "
    "Caso contrário injete o token no campo do desafio e refaça a ação. "
    "Só escale ao usuário se 422 após a cascata, login wall ou 2FA."
)


def _response_text(payload: dict) -> str:
    resp = payload.get("tool_response", "")
    if isinstance(resp, str):
        return resp
    try:
        return json.dumps(resp)
    except Exception:
        return str(resp)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # never block on malformed input

    text = _response_text(payload).lower()
    if not any(marker in text for marker in CHALLENGE_MARKERS):
        return 0

    sitekey = ""
    match = SITEKEY_RE.search(_response_text(payload))
    if match:
        sitekey = match.group(1)

    context = INSTRUCTION
    if sitekey:
        context += f" sitekey={sitekey}"

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": context,
        }
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
