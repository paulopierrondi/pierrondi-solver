#!/usr/bin/env python3
"""Quickstart: detect a challenge in a saved page and solve it via the service."""
import sys

import httpx

SOLVER = "http://127.0.0.1:8791"

# 1) you fetched a page and it came back with a challenge
html = open(sys.argv[1]).read() if len(sys.argv) > 1 else ""
url = sys.argv[2] if len(sys.argv) > 2 else "https://example.com"

from pierrondi_solver.client import detect_challenge, solve_verbose

challenge = detect_challenge(html, url)
if challenge is None:
    print("no challenge detected")
    raise SystemExit(0)

print(f"detected: type={challenge.type} sitekey={challenge.sitekey or '(none — interstitial)'}")
result = solve_verbose(challenge)
if result["solved"]:
    print(f"SOLVED via {result['provider']}/{result['strategy']} "
          f"in {result['latency_ms']}ms (cost ${result['cost_usd']})")
    if result.get("extra", {}).get("cookies"):
        print("cloudflare clearance: reuse cookies + user_agent from `extra` on the same IP")
    else:
        print(f"token: {result['token'][:40]}...")
else:
    print(f"unsolved: {result.get('reason', '')[:200]}")
