// Package solverclient is a minimal, typed Go client for the Python
// pierrondi-solver HTTP API. It mirrors the request/response contract of
// POST /solve and GET /health without reimplementing any solving logic.
//
// The client enforces locally the same invariants the Python API enforces
// with Pydantic, plus two artifact-policy rules: a returned artifact_policy
// purpose must equal the requested purpose, and a non-Cloudflare result must
// be single_use.
//
// Cloudflare clearance is session_bound: the returned cookie, the user agent
// and the originating IP form one identity. Callers must reuse all three
// together and must not treat a clearance as a portable token.
//
// The client never retries, never logs, and its error strings never contain
// tokens, cookies, sitekeys, operation IDs, or response bodies.
package solverclient

import (
	"encoding/json"
)

// ChallengeType identifies the challenge family to solve.
type ChallengeType string

// Supported challenge types, mirroring the Python ChallengeType enum.
const (
	ChallengeRecaptchaV2 ChallengeType = "recaptcha_v2"
	ChallengeRecaptchaV3 ChallengeType = "recaptcha_v3"
	ChallengeHCaptcha    ChallengeType = "hcaptcha"
	ChallengeTurnstile   ChallengeType = "turnstile"
	// ChallengeCloudflare is the interstitial/IUAM challenge, solved via a
	// cf_clearance cookie, not a field token.
	ChallengeCloudflare ChallengeType = "cloudflare"
)

func (t ChallengeType) known() bool {
	switch t {
	case ChallengeRecaptchaV2, ChallengeRecaptchaV3, ChallengeHCaptcha,
		ChallengeTurnstile, ChallengeCloudflare:
		return true
	}
	return false
}

// Purpose is the semantic stage where the returned artifact will be consumed.
type Purpose string

// Supported purposes, mirroring the Python SolvePurpose enum.
const (
	PurposeGeneric        Purpose = "generic"
	PurposeAuthentication Purpose = "authentication"
	PurposeReadOnly       Purpose = "read_only"
	PurposeStateChange    Purpose = "state_change"
)

func (p Purpose) known() bool {
	switch p {
	case PurposeGeneric, PurposeAuthentication, PurposeReadOnly, PurposeStateChange:
		return true
	}
	return false
}

// Consumption describes how narrowly a returned artifact may be consumed.
type Consumption string

// Artifact consumption modes declared by the API.
const (
	// ConsumptionSingleUse marks token challenges: use once, for the exact
	// requested purpose, then discard.
	ConsumptionSingleUse Consumption = "single_use"
	// ConsumptionSessionBound marks Cloudflare clearance: reusable only while
	// cookie, user agent and originating IP remain one identity context.
	ConsumptionSessionBound Consumption = "session_bound"
)

// SolveRequest is the exact JSON contract of POST /solve.
type SolveRequest struct {
	Type        ChallengeType `json:"type"`
	Sitekey     string        `json:"sitekey"`
	PageURL     string        `json:"page_url"`
	Lane        string        `json:"lane"`
	TimeoutS    int           `json:"timeout_s"`
	Purpose     Purpose       `json:"purpose"`
	OperationID string        `json:"operation_id"`
	Attempt     int           `json:"attempt"`
}

// ArtifactPolicy mirrors the policy object the API embeds in
// extra.artifact_policy on success.
type ArtifactPolicy struct {
	Purpose                    Purpose     `json:"purpose"`
	OperationID                string      `json:"operation_id"`
	Attempt                    int         `json:"attempt"`
	Consumption                Consumption `json:"consumption"`
	MustNotReuseAcrossPurposes bool        `json:"must_not_reuse_across_purposes"`
}

// SolveResult is the decoded HTTP 200 response of POST /solve.
//
// Token is the solved artifact: a challenge token for token challenges, or
// the clearance context for Cloudflare (see Extra for user agent/cookies).
// Artifact is the typed view of extra.artifact_policy; Extra retains the raw
// map for forward-compatible fields such as engine or cookies.
type SolveResult struct {
	Token     string
	Strategy  string
	Provider  string
	LatencyMs int
	CostUSD   float64
	Extra     map[string]json.RawMessage
	Artifact  ArtifactPolicy
}

// UnmarshalJSON decodes the wire format and lifts extra.artifact_policy into
// the typed Artifact field.
func (r *SolveResult) UnmarshalJSON(data []byte) error {
	var wire struct {
		Token     string                     `json:"token"`
		Strategy  string                     `json:"strategy"`
		Provider  string                     `json:"provider"`
		LatencyMs int                        `json:"latency_ms"`
		CostUSD   float64                    `json:"cost_usd"`
		Extra     map[string]json.RawMessage `json:"extra"`
	}
	if err := json.Unmarshal(data, &wire); err != nil {
		return err
	}
	r.Token = wire.Token
	r.Strategy = wire.Strategy
	r.Provider = wire.Provider
	r.LatencyMs = wire.LatencyMs
	r.CostUSD = wire.CostUSD
	r.Extra = wire.Extra
	r.Artifact = ArtifactPolicy{}
	if raw, ok := wire.Extra["artifact_policy"]; ok {
		if err := json.Unmarshal(raw, &r.Artifact); err != nil {
			return err
		}
	}
	return nil
}

// UnsolvedError is the structured HTTP 422 response of POST /solve.
//
// It implements error. The Error string is deliberately redacted: it carries
// only static shape information, never the server-provided Reason or Attempts
// text, because those fields are server-controlled and could echo sensitive
// request material. Read the typed fields programmatically when needed.
type UnsolvedError struct {
	// Kind is the wire "error" field (always "unsolved" today); named Kind
	// so the type can implement the error interface.
	Kind                string   `json:"error"`
	Reason              string   `json:"reason"`
	FallbackRecommended bool     `json:"fallback_recommended"`
	Attempts            []string `json:"attempts"`
}

// Error returns a redacted, secret-free description.
func (e *UnsolvedError) Error() string {
	return "solverclient: challenge unsolved"
}

// HealthResult is the typed response of GET /health.
type HealthResult struct {
	Status    string   `json:"status"`
	Providers []string `json:"providers"`
}
