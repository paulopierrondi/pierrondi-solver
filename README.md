# pierrondi-solver

**Self-hosted CAPTCHA + Cloudflare solving service, built for AI agents.**
Local-first ($0/solve), with automatic commercial fallback, circuit breaker, and cost telemetry.

```
POST /solve  { "type": "recaptcha_v2|recaptcha_v3|hcaptcha|turnstile|cloudflare",
               "sitekey": "...", "page_url": "..." }
200 { "token": "...", "strategy": "v2_audio", "provider": "pierrondi", "cost_usd": 0.0,
      "extra": { "cookies": {"cf_clearance": "..."}, "user_agent": "..." } }
422 { "error": "unsolved", "reason": "...", "fallback_recommended": true }
```

## Why this exists

Existing tools solve **one** problem each: FlareSolverr does Cloudflare clearance but no CAPTCHA tokens,
whisper-based repos do reCAPTCHA v2 but no Cloudflare, commercial SDKs cost money per call with no local tier.
**pierrondi-solver is the only one that unifies all of it behind one HTTP API**, designed from day one to be
called by AI coding agents (Claude Code, Codex, Cursor, custom bots) without human babysitting.

## What it solves

| Challenge | Local strategy ($0) | Commercial fallback | Status |
|---|---|---|---|
| reCAPTCHA v2 | Audio challenge → **faster-whisper** on CPU | CapSolver / 2Captcha / CapMonster | ✅ validated live (Google demo, ~14s) |
| Cloudflare IUAM ("Just a moment") | Stealth Chromium harvests **`cf_clearance`** + UA | CapSolver `AntiCloudflareTask` (needs residential proxy) | ✅ validated live (~5s) |
| Turnstile / hCaptcha | — | ✅ wired | ready (needs API key) |
| reCAPTCHA v3 | Honest by design: v3 is **score-based**, no token — mitigation guidance | ✅ wired | documented |

## The differentiators (vs FlareSolverr, uncaptcha, whisper repos)

1. **Provider cascade with circuit breaker** — `pierrondi (local, $0) → capsolver → 2captcha → capmonster`.
   A provider opens its breaker at >30% failures/hour and the chain skips it automatically.
2. **Cost + success telemetry built in** — every attempt logged to SQLite (tokens stored only as truncated
   hashes), exposed at `GET /metrics` with per-provider success rate, latency and USD cost.
3. **Agent-native** — ships a client CLI (`pierrondi-solve detect|solve|health|doctor`), an HTML challenge
   detector (extracts sitekey / classifies CF interstitial vs Turnstile), and a ready Claude Code
   `PostToolUse` hook that auto-solves challenges found in tool output **without asking the human**.
4. **Honest engineering** — reCAPTCHA v3 is documented as score-based (no fake "v3 solving");
   image-tile strategy ships as an explicit stub instead of silent failure; unsolved responses carry
   structured reasons for every attempt.
5. **`doctor` self-audit** — one command checks env, service, LaunchAgent, deps, chromium binary and
   key presence (never values).

## Quickstart

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,local-solve]'
playwright install chromium
uvicorn pierrondi_solver.main:app --port 8791 --app-dir src
```

```bash
# one-shot stack audit
pierrondi-solve doctor

# detect a challenge in saved HTML
pierrondi-solve detect --html-file page.html --url https://example.com

# solve via the service
pierrondi-solve solve --type recaptcha_v2 --sitekey 6Lc... --url https://example.com/form
```

Python client:

```python
from pierrondi_solver.client import Challenge, solve_verbose
result = solve_verbose(Challenge("cloudflare", "", "https://protected-site.com"))
if result["solved"]:
    cookie = result["extra"]["cookies"]["cf_clearance"]
    ua = result["extra"]["user_agent"]      # reuse cookie + UA from the same IP
```

## Config (env only — secrets never in files)

| Var | Default | Purpose |
|---|---|---|
| `PIERRONDI_SOLVER_URL` | `http://127.0.0.1:8791` | client-side endpoint |
| `CAPTCHA_PROVIDER` | `auto` | `auto` = local → capsolver → 2captcha → capmonster, or pin one |
| `CAPSOLVER_API_KEY` / `TWOCAPTCHA_API_KEY` / `CAPMONSTER_API_KEY` | — | commercial fallback keys |
| `CAPSOLVER_PROXY` | — | residential proxy (required for `AntiCloudflareTask`) |
| `SOLVER_BREAKER_FAILURE_RATE` | `0.30` | circuit-breaker threshold |

## Claude Code auto-solve hook

`hooks/captcha_posttool_hook.py` — register it as a `PostToolUse` hook; when a browser tool's output
contains CAPTCHA/Cloudflare markers, the agent gets the solve instruction (with the sitekey already
extracted) and resolves silently. See `examples/claude-code-hook.md`.

## Tests

```bash
pytest -q     # 61 tests: breaker, telemetry, chain, API contract, client, hook, strategies
```

## Responsible use

This project is for **your own accounts, QA/testing and authorized automation**. Solving CAPTCHAs may
violate target sites' Terms of Service. Never use it against third-party sites you don't control,
for mass account creation, or to bypass 2FA/login walls — the service refuses those flows by policy.
Commercial-solver pricing shown in telemetry is approximate.

## License

MIT — see [LICENSE](LICENSE).
