# solverclient — Go client for pierrondi-solver

Minimal, typed Go client for the Python `pierrondi-solver` HTTP API. It
mirrors the `POST /solve` and `GET /health` contracts; it does **not**
reimplement any solving logic. Python remains the challenge-resolution core,
Go is the orchestration edge.

## Guarantees

- Typed `ChallengeType` / `Purpose` constants mirroring the Python enums.
- Local validation before any network I/O (sitekey rule, `timeout_s` 5–600,
  `attempt` 1–1000, `operation_id` pattern, known type/purpose).
- Context cancellation and deadlines propagate to `net/http`.
- Bounded response-body reads (1 MiB).
- **No automatic retry.** Exactly one HTTP request per call, including
  `state_change` on 5xx. Retrying is the caller's business decision.
- Redacted errors: `Error()` strings never contain tokens, cookies, sitekeys,
  operation IDs, or response bodies.
- Artifact-policy enforcement: a returned `artifact_policy` purpose must
  equal the requested purpose; non-Cloudflare results must be `single_use`;
  Cloudflare results must be `session_bound`.

## Install

```bash
go get github.com/paulopierrondi/pierrondi-solver/clients/go
```

## Example — authentication stage

```go
package main

import (
	"context"
	"fmt"
	"time"

	solverclient "github.com/paulopierrondi/pierrondi-solver/clients/go"
)

func main() {
	client, err := solverclient.New("http://127.0.0.1:8787")
	if err != nil {
		panic(err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Second)
	defer cancel()

	result, err := client.Solve(ctx, solverclient.SolveRequest{
		Type:        solverclient.ChallengeRecaptchaV2,
		Sitekey:     "6Le-example-sitekey",
		PageURL:     "https://example.com/login",
		Lane:        "default",
		TimeoutS:    120,
		Purpose:     solverclient.PurposeAuthentication,
		OperationID: "login-flow-001",
		Attempt:     1,
	})
	if err != nil {
		// err is redacted: safe to log. Use errors.As for typed handling
		// (*solverclient.UnsolvedError, *HTTPError, *ValidationError, ...).
		panic(err)
	}

	// single_use token: consume once, for this exact purpose, then discard.
	fmt.Println("solved by", result.Provider, "in", result.LatencyMs, "ms")
}
```

## Example — read_only stage

```go
result, err := client.Solve(ctx, solverclient.SolveRequest{
	Type:     solverclient.ChallengeTurnstile,
	Sitekey:  "0x4-example-sitekey",
	PageURL:  "https://example.com/pricing",
	Lane:     "default",
	TimeoutS: 120,
	Purpose:  solverclient.PurposeReadOnly,
	Attempt:  1,
})
```

## Cloudflare clearance is session-bound

For `ChallengeCloudflare` the API returns a clearance context in `extra`
(`cookies.cf_clearance`, `user_agent`). The cookie, the user agent and the
originating IP are **one identity**: reuse all three together, from the same
egress IP, or the clearance is void. Do not treat it as a portable token, do
not move it across purposes, lanes, or machines. The client surfaces this as
`Artifact.Consumption == solverclient.ConsumptionSessionBound`.

## Health

```go
health, err := client.Health(ctx)
// health.Status, health.Providers
```

## Live smoke

Zero-cost probes against the running local service (health plus the
stage-aware 422 rejections; no valid solve payload is ever sent). Requires
both the build tag and the env guard:

```bash
SOLVER_LIVE_SMOKE=1 go test -tags live -run LiveSmoke -v ./...
```

## Scope

Out of scope by design: worker pools, queues, browser control, retry
frameworks, and target-specific adapters. Those belong to the caller.
