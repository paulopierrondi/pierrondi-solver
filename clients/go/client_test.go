package solverclient_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	solverclient "github.com/paulopierrondi/pierrondi-solver/clients/go"
)

func validRequest() solverclient.SolveRequest {
	return solverclient.SolveRequest{
		Type:        solverclient.ChallengeRecaptchaV2,
		Sitekey:     "6Le-example-sitekey",
		PageURL:     "https://example.com/login",
		Lane:        "default",
		TimeoutS:    120,
		Purpose:     solverclient.PurposeAuthentication,
		OperationID: "op-123",
		Attempt:     1,
	}
}

func artifactPolicy(purpose solverclient.Purpose, consumption solverclient.Consumption, mustNotReuse bool) string {
	return fmt.Sprintf(
		`{"purpose":%q,"operation_id":"op-123","attempt":1,"consumption":%q,"must_not_reuse_across_purposes":%t}`,
		purpose, consumption, mustNotReuse,
	)
}

func solvedBody(purpose solverclient.Purpose, consumption solverclient.Consumption) string {
	return `{"token":"tok-example","strategy":"audio_v2","provider":"pierrondi","latency_ms":1234,"cost_usd":0.0,` +
		`"extra":{"engine":"chromium","artifact_policy":` + artifactPolicy(purpose, consumption, consumption == solverclient.ConsumptionSingleUse) + `}}`
}

// 1. Exact JSON request contract.
func TestRequestJSONContract(t *testing.T) {
	payload, err := json.Marshal(validRequest())
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	want := `{"type":"recaptcha_v2","sitekey":"6Le-example-sitekey","page_url":"https://example.com/login","lane":"default","timeout_s":120,"purpose":"authentication","operation_id":"op-123","attempt":1}`
	if string(payload) != want {
		t.Fatalf("contract mismatch:\n got: %s\nwant: %s", payload, want)
	}
}

// 2. Success decoding, including typed artifact policy and raw extra.
func TestSolveSuccess(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/solve" {
			t.Errorf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		if ct := r.Header.Get("Content-Type"); ct != "application/json" {
			t.Errorf("unexpected content type %q", ct)
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, solvedBody(solverclient.PurposeAuthentication, solverclient.ConsumptionSingleUse))
	}))
	defer srv.Close()

	c, err := solverclient.New(srv.URL)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	res, err := c.Solve(context.Background(), validRequest())
	if err != nil {
		t.Fatalf("Solve: %v", err)
	}
	if res.Token != "tok-example" || res.Strategy != "audio_v2" || res.Provider != "pierrondi" {
		t.Fatalf("unexpected result: %+v", res)
	}
	if res.LatencyMs != 1234 || res.CostUSD != 0.0 {
		t.Fatalf("unexpected metrics: %+v", res)
	}
	if res.Artifact.Purpose != solverclient.PurposeAuthentication ||
		res.Artifact.Consumption != solverclient.ConsumptionSingleUse ||
		!res.Artifact.MustNotReuseAcrossPurposes {
		t.Fatalf("unexpected artifact policy: %+v", res.Artifact)
	}
	if _, ok := res.Extra["engine"]; !ok {
		t.Fatalf("raw extra lost: %v", res.Extra)
	}
}

// 3. Structured 422 decoding.
func TestSolveUnsolved422(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusUnprocessableEntity)
		fmt.Fprint(w, `{"error":"unsolved","reason":"all providers failed","fallback_recommended":true,"attempts":["pierrondi: no audio","capsolver: timeout"]}`)
	}))
	defer srv.Close()

	c, _ := solverclient.New(srv.URL)
	res, err := c.Solve(context.Background(), validRequest())
	if res != nil {
		t.Fatalf("expected nil result, got %+v", res)
	}
	var unsolved *solverclient.UnsolvedError
	if !errors.As(err, &unsolved) {
		t.Fatalf("expected *UnsolvedError, got %T (%v)", err, err)
	}
	if unsolved.Reason != "all providers failed" || !unsolved.FallbackRecommended || len(unsolved.Attempts) != 2 {
		t.Fatalf("unexpected decode: %+v", unsolved)
	}
}

// 4. Malformed and oversized response handling.
func TestSolveMalformedJSON(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, `this is not json`)
	}))
	defer srv.Close()

	c, _ := solverclient.New(srv.URL)
	res, err := c.Solve(context.Background(), validRequest())
	if res != nil || err == nil {
		t.Fatalf("expected error, got res=%+v err=%v", res, err)
	}
	var respErr *solverclient.ResponseError
	if !errors.As(err, &respErr) {
		t.Fatalf("expected *ResponseError, got %T (%v)", err, err)
	}
}

func TestSolveOversizedResponse(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, strings.Repeat("x", (1<<20)+16))
	}))
	defer srv.Close()

	c, _ := solverclient.New(srv.URL)
	res, err := c.Solve(context.Background(), validRequest())
	if res != nil || err == nil {
		t.Fatalf("expected error, got res=%+v err=%v", res, err)
	}
	var respErr *solverclient.ResponseError
	if !errors.As(err, &respErr) {
		t.Fatalf("expected *ResponseError, got %T (%v)", err, err)
	}
}

// 5. Context cancellation propagates to net/http.
func TestSolveContextCancellation(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-r.Context().Done():
		case <-time.After(2 * time.Second):
		}
	}))
	defer srv.Close()

	c, _ := solverclient.New(srv.URL)
	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		time.Sleep(50 * time.Millisecond)
		cancel()
	}()
	_, err := c.Solve(ctx, validRequest())
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("expected context.Canceled, got %v", err)
	}
}

// 6. Context deadline propagates to net/http.
func TestSolveContextTimeout(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(500 * time.Millisecond)
		fmt.Fprint(w, solvedBody(solverclient.PurposeAuthentication, solverclient.ConsumptionSingleUse))
	}))
	defer srv.Close()

	c, _ := solverclient.New(srv.URL)
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	_, err := c.Solve(ctx, validRequest())
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("expected context.DeadlineExceeded, got %v", err)
	}
}

// 7. Invalid purpose/type/sitekey/attempt/operation_id fail before any I/O.
func TestSolveValidation(t *testing.T) {
	var hits atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		fmt.Fprint(w, solvedBody(solverclient.PurposeAuthentication, solverclient.ConsumptionSingleUse))
	}))
	defer srv.Close()

	c, _ := solverclient.New(srv.URL)

	cases := map[string]func(*solverclient.SolveRequest){
		"unknown type":           func(r *solverclient.SolveRequest) { r.Type = "recaptcha_v9" },
		"unknown purpose":        func(r *solverclient.SolveRequest) { r.Purpose = "write_only" },
		"missing sitekey":        func(r *solverclient.SolveRequest) { r.Sitekey = "" },
		"timeout too low":        func(r *solverclient.SolveRequest) { r.TimeoutS = 4 },
		"timeout too high":       func(r *solverclient.SolveRequest) { r.TimeoutS = 601 },
		"attempt too low":        func(r *solverclient.SolveRequest) { r.Attempt = 0 },
		"attempt too high":       func(r *solverclient.SolveRequest) { r.Attempt = 1001 },
		"operation_id bad start": func(r *solverclient.SolveRequest) { r.OperationID = "-op123" },
		"operation_id too long":  func(r *solverclient.SolveRequest) { r.OperationID = strings.Repeat("a", 81) },
		"operation_id bad char":  func(r *solverclient.SolveRequest) { r.OperationID = "op 123" },
		"page_url too short":     func(r *solverclient.SolveRequest) { r.PageURL = "http://" },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			req := validRequest()
			mutate(&req)
			res, err := c.Solve(context.Background(), req)
			if res != nil || err == nil {
				t.Fatalf("expected validation error, got res=%+v err=%v", res, err)
			}
			var valErr *solverclient.ValidationError
			if !errors.As(err, &valErr) {
				t.Fatalf("expected *ValidationError, got %T (%v)", err, err)
			}
		})
	}

	validOps := []string{"", "abc", "A1.-:_z9", strings.Repeat("b", 80)}
	for _, op := range validOps {
		req := validRequest()
		req.OperationID = op
		if _, err := c.Solve(context.Background(), req); err != nil {
			t.Fatalf("operation_id %q should be valid: %v", op, err)
		}
	}

	if got := hits.Load(); got != int32(len(validOps)) {
		t.Fatalf("server hit %d times, want %d (invalid requests must never reach the network)", got, len(validOps))
	}
}

// 8. Artifact-policy mismatch is rejected.
func TestArtifactPolicyMismatch(t *testing.T) {
	cases := map[string]struct {
		req  solverclient.SolveRequest
		body string
	}{
		"purpose mismatch": {
			req:  validRequest(),
			body: solvedBody(solverclient.PurposeReadOnly, solverclient.ConsumptionSingleUse),
		},
		"non-cloudflare not single_use": {
			req:  validRequest(),
			body: solvedBody(solverclient.PurposeAuthentication, solverclient.ConsumptionSessionBound),
		},
		"cloudflare not session_bound": {
			req: func() solverclient.SolveRequest {
				r := validRequest()
				r.Type = solverclient.ChallengeCloudflare
				r.Sitekey = ""
				return r
			}(),
			body: solvedBody(solverclient.PurposeAuthentication, solverclient.ConsumptionSingleUse),
		},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				fmt.Fprint(w, tc.body)
			}))
			defer srv.Close()

			c, _ := solverclient.New(srv.URL)
			res, err := c.Solve(context.Background(), tc.req)
			if res != nil || err == nil {
				t.Fatalf("expected policy error, got res=%+v err=%v", res, err)
			}
			var polErr *solverclient.ArtifactPolicyError
			if !errors.As(err, &polErr) {
				t.Fatalf("expected *ArtifactPolicyError, got %T (%v)", err, err)
			}
		})
	}
}

// 9. Cloudflare session_bound semantics: no sitekey required, session_bound
// accepted, clearance context preserved in extra.
func TestCloudflareSessionBound(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var got map[string]any
		if err := json.NewDecoder(r.Body).Decode(&got); err != nil {
			t.Errorf("decode request: %v", err)
		}
		if got["sitekey"] != "" {
			t.Errorf("cloudflare must send empty sitekey, got %v", got["sitekey"])
		}
		body := `{"token":"cf-clearance-context","strategy":"clearance","provider":"pierrondi","latency_ms":4321,"cost_usd":0.0,` +
			`"extra":{"user_agent":"ua-example","cookies":{"cf_clearance":"cookie-example"},"artifact_policy":` +
			artifactPolicy(solverclient.PurposeReadOnly, solverclient.ConsumptionSessionBound, false) + `}}`
		fmt.Fprint(w, body)
	}))
	defer srv.Close()

	c, _ := solverclient.New(srv.URL)
	req := validRequest()
	req.Type = solverclient.ChallengeCloudflare
	req.Sitekey = ""
	req.Purpose = solverclient.PurposeReadOnly

	res, err := c.Solve(context.Background(), req)
	if err != nil {
		t.Fatalf("Solve: %v", err)
	}
	if res.Artifact.Consumption != solverclient.ConsumptionSessionBound {
		t.Fatalf("expected session_bound, got %+v", res.Artifact)
	}
	if res.Artifact.MustNotReuseAcrossPurposes {
		t.Fatalf("session_bound artifact must allow same-purpose persistence: %+v", res.Artifact)
	}
	if _, ok := res.Extra["cookies"]; !ok {
		t.Fatalf("clearance cookies missing from extra: %v", res.Extra)
	}
}

// 10. state_change is sent exactly once, even when the server returns 5xx.
func TestStateChangeSentOnceOn5xx(t *testing.T) {
	var hits atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		w.WriteHeader(http.StatusInternalServerError)
		fmt.Fprint(w, `{"detail":"boom"}`)
	}))
	defer srv.Close()

	c, _ := solverclient.New(srv.URL)
	req := validRequest()
	req.Purpose = solverclient.PurposeStateChange

	res, err := c.Solve(context.Background(), req)
	if res != nil {
		t.Fatalf("expected nil result, got %+v", res)
	}
	var httpErr *solverclient.HTTPError
	if !errors.As(err, &httpErr) || httpErr.StatusCode != http.StatusInternalServerError {
		t.Fatalf("expected *HTTPError 500, got %T (%v)", err, err)
	}
	if got := hits.Load(); got != 1 {
		t.Fatalf("state_change sent %d times, want exactly 1 (no implicit retry)", got)
	}
}

// 11. Errors never contain token, cookie, sitekey, or operation_id values.
func TestErrorsRedacted(t *testing.T) {
	const (
		secretSitekey = "SITEKEY-SECRET-9f8e7d"
		secretOpID    = "OPID-SECRET-7d6c5b"
		secretToken   = "TOKEN-SECRET-1a2b3c"
		secretCookie  = "COOKIE-SECRET-4d5e6f"
	)
	secrets := []string{secretSitekey, secretOpID, secretToken, secretCookie}
	assertRedacted := func(t *testing.T, err error) {
		t.Helper()
		if err == nil {
			t.Fatal("expected error")
		}
		for _, s := range secrets {
			if strings.Contains(err.Error(), s) {
				t.Fatalf("error leaked secret material: %q contains %q", err.Error(), s)
			}
		}
	}

	echoBody := `{"error":"unsolved","reason":"provider echoed ` + secretSitekey + ` and ` + secretToken + `",` +
		`"fallback_recommended":false,"attempts":["saw ` + secretOpID + `","saw ` + secretCookie + `"]}`

	t.Run("422 echo", func(t *testing.T) {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusUnprocessableEntity)
			fmt.Fprint(w, echoBody)
		}))
		defer srv.Close()
		c, _ := solverclient.New(srv.URL)
		req := validRequest()
		req.Sitekey = secretSitekey
		req.OperationID = secretOpID
		_, err := c.Solve(context.Background(), req)
		assertRedacted(t, err)
	})

	t.Run("5xx echo", func(t *testing.T) {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusBadGateway)
			fmt.Fprint(w, echoBody)
		}))
		defer srv.Close()
		c, _ := solverclient.New(srv.URL)
		req := validRequest()
		req.Sitekey = secretSitekey
		req.OperationID = secretOpID
		_, err := c.Solve(context.Background(), req)
		assertRedacted(t, err)
	})

	t.Run("malformed echo", func(t *testing.T) {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			fmt.Fprint(w, secretSitekey+secretToken)
		}))
		defer srv.Close()
		c, _ := solverclient.New(srv.URL)
		req := validRequest()
		req.Sitekey = secretSitekey
		req.OperationID = secretOpID
		_, err := c.Solve(context.Background(), req)
		assertRedacted(t, err)
	})

	t.Run("validation echo", func(t *testing.T) {
		c, _ := solverclient.New("http://127.0.0.1:1")
		req := validRequest()
		req.Sitekey = secretSitekey
		req.OperationID = "-" + secretOpID
		_, err := c.Solve(context.Background(), req)
		assertRedacted(t, err)
	})
}

// Strict base URL validation.
func TestNewBaseURLValidation(t *testing.T) {
	invalid := []string{"", "example.com", "ftp://example.com", "http://", "http://user:pw@example.com", "http://example.com?x=1", "http://example.com#frag", "::bad::"}
	for _, raw := range invalid {
		if _, err := solverclient.New(raw); err == nil {
			t.Fatalf("base URL %q should be rejected", raw)
		}
	}
	valid := []string{"http://127.0.0.1:8787", "https://example.com", "http://example.com/"}
	for _, raw := range valid {
		if _, err := solverclient.New(raw); err != nil {
			t.Fatalf("base URL %q should be accepted: %v", raw, err)
		}
	}
}

// Health decoding.
func TestHealth(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/health" {
			t.Errorf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		fmt.Fprint(w, `{"status":"ok","providers":["pierrondi","capsolver"]}`)
	}))
	defer srv.Close()

	c, _ := solverclient.New(srv.URL)
	health, err := c.Health(context.Background())
	if err != nil {
		t.Fatalf("Health: %v", err)
	}
	if health.Status != "ok" || len(health.Providers) != 2 || health.Providers[0] != "pierrondi" {
		t.Fatalf("unexpected health: %+v", health)
	}
}
