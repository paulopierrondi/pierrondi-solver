# Competitive landscape — focused tools vs an integrated agent layer (2026-07)

This snapshot explains product trade-offs, not an absolute or permanent
uniqueness claim. The central difference is packaging: `pierrondi-solver`
combines local CAPTCHA paths, Cloudflare clearance, commercial fallback,
circuit breaking, cost telemetry, and agent interfaces behind one contract.
Most alternatives deliberately focus on one part of that stack.

| Project | reCAPTCHA v2 | Cloudflare IUAM | Commercial fallback | Circuit breaker | Cost telemetry | Agent-native | Service API |
|---|---|---|---|---|---|---|---|
| **pierrondi-solver** | ✅ whisper local | ✅ cf_clearance | ✅ 3 providers | ✅ | ✅ SQLite + /metrics | ✅ CLI + hook | ✅ FastAPI |
| FlareSolverr | ❌ (no tokens) | ✅ (degrades vs managed) | partial (manual wiring) | ❌ | ❌ | ❌ | ✅ proxy |
| ibedevesh/capsolver | ✅ whisper local | ❌ | ❌ | ❌ | ❌ | partial (lib) | ❌ library |
| saifyxpro/recaptcha-v2-audio-solver | ✅ selenium+whisper | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ library |
| Theyka/Turnstile-Solver | ❌ | turnstile only | ❌ | ❌ | ❌ | ❌ | ❌ |
| ecthros/uncaptcha(2) | ✅ (2017-18, unmaintained) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ academic |
| aydinnyunus/ai-captcha-bypass | ✅ (paid GPT-4o/Gemini) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 2captcha/capsolver SDKs | ✅ paid only | ✅ paid only | ✅ (they are one) | ❌ | partial | ❌ | ❌ client lib |

## Where each alternative stops (and we continue)

- **FlareSolverr** — the standard for Cloudflare, but: no CAPTCHA token solving natively,
  degrades against managed/interactive challenges, no local/ paid hybrid cascade, no per-provider
  success/cost accounting. Ours does clearance *and* tokens, and tells you what every attempt cost.
- **ibedevesh/capsolver** (Feb 2026, "for AI Agents") — close in spirit for v2 audio+whisper,
  but it's a library, v2-only: no service, no Cloudflare, no fallback chain, no breaker, no telemetry,
  no hook integration. `pierrondi-solver` provides a broader operational surface.
- **uncaptcha/uncaptcha2** — the academic origin (USENIX WOOT'17, 85-91%). Unmaintained;
  Google has iterated since. We use the same audio insight with modern faster-whisper on CPU,
  stealth browser context, and production plumbing around it.
- **Commercial SDKs** — reliable but pay-per-solve with no free local tier and no unified
  local-first routing. Ours treats them as what they should be: the fallback, not the default.

## Honest weaknesses (ours, today)

- Single-machine service (no queue/proxy pool); high-volume scraping should add workers + proxies.
- hCaptcha/Turnstile are commercial-only (no local strategy yet).
- reCAPTCHA v2 image-tile strategy is an explicit stub (audio covers the common case).
- Audio challenge can be withheld by Google on flagged IPs → that's exactly why the
  commercial cascade exists (bring your own keys).
- Cloudflare clearance is bound to UA+IP; callers must reuse both (documented, returned in `extra`).

## Positioning statement (for the repo description)

> The only self-hosted solver that unifies reCAPTCHA (audio+whisper, $0) and Cloudflare
> clearance behind one HTTP API — with commercial fallback cascade, circuit breaker,
> cost telemetry, and first-class AI-agent integration. Built so agents resolve
> challenges silently instead of stopping to ask a human.
