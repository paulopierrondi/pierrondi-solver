# X Posts — Batch 1 — pierrondi-solver

Audience: devs / agent builders. Voice: engineer-to-engineer, dry, numbers first, honest limits.
All facts verified live 2026-07-30. Max 1 emoji per post. Repo link in ≤6 posts.

---

## 1. Numbers-first launch

Self-hosted CAPTCHA solver for AI agents, live matrix:

- reCAPTCHA v2: 14.1s
- reCAPTCHA v3: 4.5s
- hCaptcha: 7.2s
- Turnstile: 4.5s
- Cloudflare clearance

All solved locally. $0 per solve. MIT.

github.com/paulopierrondi/pierrondi-solver

## 2. Pain angle

Your agent hits a CAPTCHA and either dies or starts paying $1–3 per 1,000 solves to a third-party API.

pierrondi-solver is the third option: one POST /solve, solved on your own box, commercial solvers demoted to optional fallback.

## 3. Contrarian / local-first

Most solver SDKs treat 2captcha as the product and local solving as the demo.

I flipped it: local-first is the default, commercial providers (2captcha, CapSolver, CapMonster) are optional fallbacks you wire in only if you want them.

Your keys, your cost, your call.

## 4. Thread (1/3) — How it works

How pierrondi-solver is put together 🧵

One HTTP API: POST /solve. Behind it: circuit breaker, cost telemetry, and a local solving engine. No raw tokens stored anywhere — telemetry tracks cost, not secrets.

## 4. Thread (2/3)

The identity layer is the part people skip: cookie + UA + IP are treated as ONE identity. Cloudflare clearance is session-bound to all three — rotate one and the session is invalid. So the proxy layer fails closed and only logs an 8-char fingerprint.

## 4. Thread (3/3)

Clients: typed Go client (clients/go) and a Node client. Same validation, same artifact policy, same redacted errors, zero implicit retries. state_change is sent exactly once.

MIT: github.com/paulopierrondi/pierrondi-solver

## 5. Security / build-in-public

TIL while pinning deps: the official MCP SDK 2.0.0 restructure broke our import path on release day) is one unit, ambiguous states stop instead of retrying, telemetry never stores raw tokens — just an 8-char fingerprint.

Boring beats clever.

## 10. hCaptcha / accessibility

Free hCaptcha solving, the legitimate way: hCaptcha's accessibility cookie program gives qualifying users a cookie that enables an audio-challenge path.

pierrondi-solver uses it for a fully local audio solve. No paid API, no gray area — 7.2s single live run on the live matrix.

## 11. Thread (1/2) — Cost math

The math that made me build this 🧵

Commercial CAPTCHA APIs charge per 1,000 solves. An agent fleet doing retries at scale turns that into a real line item — and every solve ships your target URLs through a third party.

## 11. Thread (2/2)

pierrondi-solver runs the whole matrix locally at $0: reCAPTCHA v2 14.1s, v3 4.5s, hCaptcha 7.2s, Turnstile 4.5s, Cloudflare clearance. Commercial providers stay available as opt-in fallbacks. MIT.

github.com/paulopierrondi/pierrondi-solver

## 12. Build-in-public / honest

What pierrondi-solver won't do:

- bypass DataDome/Queue-it/Akamai/PerimeterX (it stops on sight)
- retry behind your back
- store your tokens
- pretend fallbacks are free

What it will: solve the five big challenges locally, $0, one POST /solve. That's the pitch.
