# KIMI Go Client Report — clients/go (solverclient)

Date: 2026-07-26 · Surface: Kimi CLI · Registry: `pierrondi-solver`
Branch: `feat/multi-engine-mcp-proxy-hcaptcha` (uncommitted work of
Paulo/Codex preserved untouched; the Go client is new, isolated files).

## Architecture decision

Keep Python as the challenge-resolution core; Go is the typed orchestration
edge, exactly as recommended in
[`AUTHORIZED_WORKFLOW_LESSONS.md`](./AUTHORIZED_WORKFLOW_LESSONS.md)
("Build a small Go client for the existing Python API… typed requests,
`context.Context`, explicit timeouts, zero implicit retries, redacted
errors, and contract tests against a local fake server").

`solverclient` is a stdlib-only module
(`github.com/paulopierrondi/pierrondi-solver/clients/go`, Go ≥ 1.22) that:

- mirrors the Pydantic contract with string-typed enums and exact JSON tags;
- validates requests locally before any network I/O (sitekey rule,
  `timeout_s` 5–600, `attempt` 1–1000, `operation_id` pattern
  `^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$`, known type/purpose,
  `page_url` ≥ 8 chars, strict absolute-URL base with no userinfo/query/fragment);
- performs exactly one HTTP request per call — no implicit retry, including
  `state_change` on 5xx (proven by test);
- bounds every response-body read at 1 MiB;
- lifts `extra.artifact_policy` into a typed `ArtifactPolicy` and enforces:
  returned purpose == requested purpose; non-Cloudflare ⇒ `single_use`;
  Cloudflare ⇒ `session_bound`;
- keeps `UnsolvedError`, `ValidationError`, `HTTPError`,
  `ArtifactPolicyError`, and `ResponseError` fully redacted — error strings
  never carry tokens, cookies, sitekeys, operation IDs, or response bodies
  (proven by test against a hostile echo server);
- documents Cloudflare clearance as one session-bound identity
  (cookie + user agent + originating IP).

Notable Go-specific decision: the wire field `error` is mapped to
`UnsolvedError.Kind` so the type can implement the `error` interface without
a field/method name collision.

## Files changed (all new; nothing existing modified)

| Path | Purpose |
| --- | --- |
| `clients/go/go.mod` | module definition, zero external dependencies |
| `clients/go/types.go` | `ChallengeType`, `Purpose`, `Consumption`, `SolveRequest`, `ArtifactPolicy`, `SolveResult`, `UnsolvedError`, `HealthResult` |
| `clients/go/validate.go` | local request validation mirroring the Pydantic invariants |
| `clients/go/errors.go` | redacted typed errors |
| `clients/go/client.go` | `New`, `Solve`, `Health`, bounded reads, artifact-policy checks |
| `clients/go/client_test.go` | 14 test functions covering the 11 mandated cases + base-URL and health |
| `clients/go/README.md` | usage examples (authentication, read_only) on `example.com`, Cloudflare session-bound docs |
| `docs/research/KIMI_GO_CLIENT_REPORT.md` | this report |

## Commands and exact test results

Toolchain: `go1.26.5 darwin/arm64`, installed as a user-local tarball at
`~/.local/share/go-sdk/go` (no system package manager used; the host had no
Go toolchain).

| Command | Result |
| --- | --- |
| `gofmt -l .` (clients/go) | no output — clean |
| `go vet ./...` (clients/go) | clean, 0 findings |
| `go test -race -count=1 ./...` (clients/go) | `ok … 3.856s` — **14 test functions PASS, 0 FAIL** (11 mandated cases: contract JSON, 200 decode, 422 decode, malformed+oversized, ctx cancel, ctx timeout, 11 validation sub-cases, 3 artifact-policy mismatch cases, Cloudflare session_bound, state_change sent once on 5xx, error redaction × 4 vectors) |
| `.venv/bin/pytest -q` (repo root) | **134 passed**, 1 warning (upstream Starlette/httpx deprecation) in 1.79s |
| `git diff --check` | clean |

One test-iteration fix worth recording: the cancellation test originally used
a server handler blocked on `<-r.Context().Done()` with no fallback, which
hung `httptest.Server.Close()`; the handler now has a 2 s fallback `select`,
and the client-side cancellation assertion remains the actual check. Also a
test-data bug (`"https://"` is 9 chars, not < 8) was corrected; the client
validation was correct in both cases.

## Compatibility notes

- Contract verified against `src/pierrondi_solver/models.py` (lines 10–76)
  and `main.py` (`/health`, `/solve`) on 2026-07-26: identical to the brief.
- `SolveResult.Extra` keeps the raw `map[string]json.RawMessage`, so future
  server fields (`engine`, proxy hash, cookies) remain forward-compatible.
- The client targets any Go ≥ 1.22; tested on 1.26.5.
- No Go module replaces or pins the Python side; the two evolve only through
  the HTTP contract.

## Residual risks

- Live end-to-end (`Solve` against a real local solver instance) was not run;
  all tests use `httptest` fakes. A smoke against `127.0.0.1:8787` is the
  natural next validation.
- `UnsolvedError.Reason`/`Attempts` are typed but intentionally excluded from
  `Error()`; operators needing them must read fields, not logs.
- The Go toolchain lives outside the repo (`~/.local/share/go-sdk`); CI would
  need its own Go setup if the client joins the workflow.
- `clients/` is untracked; commit remains human-gated (no push/commit done).

## Network statement

No third-party network was contacted by the client or its tests. All tests
run against `httptest.NewServer` loopback fakes and `example.com` appears
only as inert string data in fixtures and documentation. The only external
fetch in this session was the official Go toolchain tarball from `go.dev`.

## Next safe slice (max 3 bullets)

- Add a manual smoke recipe: run the Python API on `127.0.0.1:8787` and call
  `Health` + one `Solve` from a Go example, guarded behind a build tag.
- Wire `clients/go` into CI (setup-go + `go vet` / `go test -race`) in a
  separate, human-approved PR.
- Evaluate a typed `Metrics` method for `GET /metrics` once telemetry shape
  stabilizes.

```yaml
prompt_cache:
  strategy: cli-prefix-layout
  prefix_version: "2026-07-26"
  cache_key_or_tag: "paulo:pierrondi-solver:kimi:go-client:v1"
  cached_tokens: null
  notes: "Kimi CLI nao expoe telemetria de prompt cache nesta sessao."
```
