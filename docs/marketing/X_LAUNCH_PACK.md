# X Launch Pack — pierrondi-solver (2026-07-30)

Asset flagship: `videos/solver-local-zero/renders/video.mp4` (40.3s, 1920x1080, VO EN, legendas).
Prova de todos os claims: matrix live 2026-07-30 (v2 14.1s · v3 4.5s · hCaptcha 7.2s · Turnstile 4.5s · Cloudflare clearance) — tudo local, $0.

## Hook principles (X dev audience)

1. Número antes de adjetivo: "5 challenge types. $0.00." > "amazing solver".
2. O inimigo é familiar: "your pipeline died at a CAPTCHA" — todo dev de agente viveu isso.
3. Receipts, não promessa: latências reais na tela.
4. A honestidade é o diferencial: "we also built the thing that tells your agent when to STOP".

## Post principal (orgânico, com o vídeo)

```
Your agent just hit a CAPTCHA. Most pipelines die right here.

So I built the thing that doesn't:

• reCAPTCHA v2 — 14.1s
• reCAPTCHA v3 — 4.5s
• hCaptcha — 7.2s
• Turnstile — 4.5s
• Cloudflare clearance

All local. $0.00. One HTTP API.

Self-hosted, MIT, Go + Node clients, MCP server, and a WAF detector that tells your agent when to stop instead of burning your IP.

github.com/paulopierrondi/pierrondi-solver
```

## Ad variants (paid, 3 angles)

**A — Pain (conversion):**
```
Your agent runs 8 hours, dies at a CAPTCHA at hour 7.
pierrondi-solver turns that wall into one HTTP call.
5 challenge types, solved locally, $0. MIT.
```

**B — Number stack (ctr):**
```
reCAPTCHA v2: 14.1s
reCAPTCHA v3: 4.5s
hCaptcha: 7.2s
Turnstile: 4.5s
Cost: $0.00
Self-hosted solver for AI agents. MIT.
```

**C — Contrarian (engagement):**
```
Every CAPTCHA solver sells you per-solve pricing.
Mine runs on your machine and charges you nothing.
Also: it tells your agent when NOT to try.
```

## Thread (5 tweets, authority play)

```
1/ I spent the week making one thing true: every challenge type an AI agent hits, solved locally, at $0.
reCAPTCHA v2/v3, hCaptcha, Turnstile, Cloudflare. One self-hosted API. Thread with the receipts ↓

2/ The matrix, live today:
v2 14.1s · v3 4.5s · hCaptcha 7.2s · Turnstile 4.5s
Local strategies only — audio+whisper, stealth browser harvests. Commercial providers exist but stay optional fallbacks.

3/ The part nobody builds: a passive WAF detector.
DataDome/Queue-it/Akamai → the API says STOP.
Detection is not evasion. Agents that know when to stop keep your IPs and accounts alive.

4/ Typed clients so the contract survives cross-language:
Go (clients/go) and Node (solver-client.mjs) — same validation, artifact policy, redacted errors, zero implicit retry. state_change is sent exactly once.

5/ Self-hosted, MIT, MCP server for any agent runtime.
github.com/paulopierrondi/pierrondi-solver
```

## Reply-guy ammo (respostas prontas)

- "isn't this against ToS?" → "Authorized flows only. The detector literally routes DataDome/Queue-it to STOP. Evasion is not the product; continuity for your own authorized automation is."
- "2captcha exists" → "It's the fallback inside, not the default. Local tier is $0; you bring keys only if you want the cascade."
- "v3 is score-based, you can't solve it" → "Correct that there's no checkbox — we execute grecaptcha in a clean stealth browser and return the real token. Score is server-side; that caveat is in the API response."

## Cadence sugerida

- D0: post principal + vídeo (9h ou 12h BRT).
- D1: thread (authority).
- D2-D4: ads A/B/C (se rodar paid — human gate).
- D7: follow-up com métrica real ("X clones, Y stars").

## Next videos (fila, mesma factory)

1. **"The detector that says stop"** (WAF clip do frame 5 expandido, 20-30s).
2. **"Go client in 40 lines"** (code-run do clients/go, terminal aesthetic).
3. **"1-click approval queue"** (career-ops angle: automation prepares, human signs).
4. **MCP SDK 2.0 day-one break** ("the official MCP SDK shipped 2.0.0 and our import path died the same hour — the pin that saved CI" — dependency-hygiene content, honest and relatable).
