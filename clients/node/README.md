# solver-client (Node) — typed client for pierrondi-solver

Zero-dependency ESM client for the pierrondi-solver HTTP API. Same contract
and enforcement as the Go client (`clients/go`):

- `solveChallenge()` / `solverHealth()` against `POST /solve` and `GET /health`
- local validation (sitekey rule, `timeout_s` 5–600, `attempt` 1–1000,
  `operation_id` pattern, known types/purposes)
- artifact-policy enforcement: purpose match, non-Cloudflare `single_use`,
  Cloudflare `session_bound`
- redacted errors (never tokens, cookies, sitekeys, operation IDs or bodies)
- bounded 1 MiB reads, `AbortController` timeouts, **zero implicit retry**
  (`state_change` is sent exactly once, even on 5xx)
- base URL via `PIERRONDI_SOLVER_URL` (default `http://127.0.0.1:8791`)

```js
import { solveChallenge } from './solver-client.mjs';

const res = await solveChallenge({
  type: 'turnstile',
  sitekey: process.env.AUTHORIZED_TEST_SITEKEY,
  pageUrl: 'https://your-authorized-test-page.example',
  purpose: 'read_only',
});
```

Tests: `node --test clients/node/test/solver-client.test.mjs` (10/10,
local `node:http` fixtures, no external network).

Originally built for `career-ops`; the canonical home is this repo.
