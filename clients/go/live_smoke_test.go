//go:build live

package solverclient_test

// Live smoke against the always-on local solver service.
//
// Run explicitly with BOTH the build tag and the env guard:
//
//	SOLVER_LIVE_SMOKE=1 go test -tags live -run LiveSmoke -v ./...
//
// Probes are zero-cost by design: /health is free, and the invalid payloads
// are rejected with 422 during schema validation, before any strategy or
// commercial provider is engaged. No valid solve payload is ever sent here.

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"os"
	"testing"
	"time"

	solverclient "github.com/paulopierrondi/pierrondi-solver/clients/go"
)

func liveURL(t *testing.T) string {
	t.Helper()
	if os.Getenv("SOLVER_LIVE_SMOKE") != "1" {
		t.Skip("set SOLVER_LIVE_SMOKE=1 to run the live smoke")
	}
	base := os.Getenv("PIERRONDI_SOLVER_URL")
	if base == "" {
		base = "http://127.0.0.1:8791"
	}
	return base
}

func TestLiveSmokeHealth(t *testing.T) {
	client, err := solverclient.New(liveURL(t))
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	health, err := client.Health(ctx)
	if err != nil {
		t.Fatalf("Health: %v", err)
	}
	if health.Status != "ok" {
		t.Fatalf("status = %q, want ok", health.Status)
	}
	if len(health.Providers) == 0 {
		t.Fatal("providers list is empty")
	}
	t.Logf("providers: %v", health.Providers)
}

// TestLiveSmokeStageAware422 proves the running service validates the
// stage-aware contract (attempt/purpose/operation_id) before any strategy
// runs: each probe must come back 422 with zero provider cost.
func TestLiveSmokeStageAware422(t *testing.T) {
	base := liveURL(t)
	cases := map[string]string{
		"attempt below range":  `{"type":"recaptcha_v2","sitekey":"x","page_url":"https://example.com","attempt":0}`,
		"purpose outside enum": `{"type":"recaptcha_v2","sitekey":"x","page_url":"https://example.com","purpose":"bogus"}`,
		"bad operation_id":     `{"type":"recaptcha_v2","sitekey":"x","page_url":"https://example.com","operation_id":"inv alid!"}`,
	}
	for name, payload := range cases {
		t.Run(name, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			req, err := http.NewRequestWithContext(ctx, http.MethodPost, base+"/solve",
				bytes.NewBufferString(payload))
			if err != nil {
				t.Fatalf("build request: %v", err)
			}
			req.Header.Set("content-type", "application/json")
			resp, err := http.DefaultClient.Do(req)
			if err != nil {
				t.Fatalf("POST /solve: %v", err)
			}
			defer resp.Body.Close()
			if resp.StatusCode != http.StatusUnprocessableEntity {
				var body map[string]any
				_ = json.NewDecoder(resp.Body).Decode(&body)
				t.Fatalf("status = %d, want 422 (body: %v)", resp.StatusCode, body)
			}
		})
	}
}
