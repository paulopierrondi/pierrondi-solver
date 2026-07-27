package solverclient

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const (
	// defaultTimeout is the safe default HTTP timeout: slightly above the
	// API default solve budget of 120 s.
	defaultTimeout = 130 * time.Second
	// maxResponseBytes bounds every response-body read (1 MiB).
	maxResponseBytes = 1 << 20
)

// Client is a typed HTTP client for the pierrondi-solver API.
//
// A Client performs exactly one HTTP request per method call: there is no
// automatic retry of any kind. Retrying is a business decision of the
// caller, and it is especially dangerous for state_change purposes, where a
// retry can double-submit a workflow stage.
type Client struct {
	baseURL string
	http    *http.Client
}

// Option customizes a Client.
type Option func(*Client)

// WithHTTPClient replaces the underlying http.Client. The provided client is
// used as-is; per-request deadlines still come from the caller's context.
func WithHTTPClient(h *http.Client) Option {
	return func(c *Client) {
		if h != nil {
			c.http = h
		}
	}
}

// WithTimeout overrides the default 130 s HTTP timeout. Context deadlines
// still take precedence when tighter.
func WithTimeout(d time.Duration) Option {
	return func(c *Client) {
		if d > 0 {
			c.http.Timeout = d
		}
	}
}

// New builds a Client for a solver base URL such as "http://127.0.0.1:8787".
//
// The base URL must be an absolute http or https URL with a host and no
// userinfo, query, or fragment. Anything else is rejected before any network
// I/O can leak request material to an unintended endpoint.
func New(rawBaseURL string, opts ...Option) (*Client, error) {
	u, err := url.Parse(rawBaseURL)
	if err != nil {
		return nil, &ValidationError{Field: "base_url", Msg: "unparseable URL"}
	}
	if u.Scheme != "http" && u.Scheme != "https" {
		return nil, &ValidationError{Field: "base_url", Msg: "scheme must be http or https"}
	}
	if u.Host == "" {
		return nil, &ValidationError{Field: "base_url", Msg: "host is required"}
	}
	if u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return nil, &ValidationError{Field: "base_url", Msg: "userinfo, query and fragment are not allowed"}
	}
	c := &Client{
		baseURL: strings.TrimSuffix(rawBaseURL, "/"),
		http:    &http.Client{Timeout: defaultTimeout},
	}
	for _, opt := range opts {
		opt(c)
	}
	return c, nil
}

// Solve posts a validated request to POST /solve and returns the typed
// result. Context cancellation and deadlines propagate to net/http.
//
// On HTTP 200 it additionally enforces the artifact-policy invariants: the
// returned policy purpose must equal the requested purpose, and a
// non-Cloudflare result must be single_use (a Cloudflare result must be
// session_bound). On HTTP 422 the returned error is an *UnsolvedError.
// Exactly one HTTP request is made per call, regardless of status code.
func (c *Client) Solve(ctx context.Context, req SolveRequest) (*SolveResult, error) {
	if err := req.Validate(); err != nil {
		return nil, err
	}
	payload, err := json.Marshal(req)
	if err != nil {
		return nil, &ValidationError{Field: "request", Msg: "cannot encode"}
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/solve", bytes.NewReader(payload))
	if err != nil {
		return nil, &ValidationError{Field: "base_url", Msg: "cannot build request"}
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Accept", "application/json")

	resp, err := c.http.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("solverclient: solve request failed: %w", redactURLError(err))
	}
	defer resp.Body.Close()

	body, err := readBounded(resp.Body)
	if err != nil {
		return nil, err
	}

	switch resp.StatusCode {
	case http.StatusOK:
		var result SolveResult
		if err := json.Unmarshal(body, &result); err != nil {
			return nil, &ResponseError{Msg: "malformed JSON body"}
		}
		if err := checkArtifactPolicy(req, &result); err != nil {
			return nil, err
		}
		return &result, nil
	case http.StatusUnprocessableEntity:
		var unsolved UnsolvedError
		if err := json.Unmarshal(body, &unsolved); err != nil {
			return nil, &ResponseError{Msg: "malformed JSON body"}
		}
		return nil, &unsolved
	default:
		return nil, &HTTPError{StatusCode: resp.StatusCode}
	}
}

// Health calls GET /health and returns the typed status and provider chain.
func (c *Client) Health(ctx context.Context) (*HealthResult, error) {
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+"/health", nil)
	if err != nil {
		return nil, &ValidationError{Field: "base_url", Msg: "cannot build request"}
	}
	httpReq.Header.Set("Accept", "application/json")

	resp, err := c.http.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("solverclient: health request failed: %w", redactURLError(err))
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, &HTTPError{StatusCode: resp.StatusCode}
	}
	body, err := readBounded(resp.Body)
	if err != nil {
		return nil, err
	}
	var health HealthResult
	if err := json.Unmarshal(body, &health); err != nil {
		return nil, &ResponseError{Msg: "malformed JSON body"}
	}
	return &health, nil
}

// readBounded reads at most maxResponseBytes from r.
func readBounded(r io.Reader) ([]byte, error) {
	body, err := io.ReadAll(io.LimitReader(r, maxResponseBytes+1))
	if err != nil {
		return nil, &ResponseError{Msg: "cannot read body"}
	}
	if len(body) > maxResponseBytes {
		return nil, &ResponseError{Msg: "body exceeds 1 MiB limit"}
	}
	return body, nil
}

// checkArtifactPolicy enforces the local artifact invariants on a 200 result.
func checkArtifactPolicy(req SolveRequest, res *SolveResult) error {
	if res.Artifact.Purpose != req.Purpose {
		return &ArtifactPolicyError{Msg: "returned purpose differs from requested purpose"}
	}
	if req.Type == ChallengeCloudflare {
		if res.Artifact.Consumption != ConsumptionSessionBound {
			return &ArtifactPolicyError{Msg: "cloudflare result must be session_bound"}
		}
		return nil
	}
	if res.Artifact.Consumption != ConsumptionSingleUse {
		return &ArtifactPolicyError{Msg: "non-cloudflare result must be single_use"}
	}
	return nil
}

// redactURLError strips the URL (which embeds no credentials by construction
// but may embed user-controlled path material in future callers) from
// *url.Error wrappers.
func redactURLError(err error) error {
	var urlErr *url.Error
	if errors.As(err, &urlErr) {
		return fmt.Errorf("%s: %w", urlErr.Op, urlErr.Err)
	}
	return err
}
