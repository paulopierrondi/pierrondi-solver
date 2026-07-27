package solverclient

import "fmt"

// ValidationError reports a locally rejected request field. Its message
// identifies the field and the rule, never the offending value.
type ValidationError struct {
	Field string
	Msg   string
}

// Error returns a redacted, value-free description.
func (e *ValidationError) Error() string {
	return fmt.Sprintf("solverclient: invalid %s: %s", e.Field, e.Msg)
}

// HTTPError reports a non-200/non-422 status from the API. It never carries
// the response body.
type HTTPError struct {
	StatusCode int
}

// Error returns a redacted, body-free description.
func (e *HTTPError) Error() string {
	return fmt.Sprintf("solverclient: unexpected HTTP status %d", e.StatusCode)
}

// ArtifactPolicyError reports a successful response whose artifact_policy
// violates a local invariant (purpose mismatch or wrong consumption mode).
// It never carries token, cookie, sitekey, or operation ID material.
type ArtifactPolicyError struct {
	Msg string
}

// Error returns a redacted, secret-free description.
func (e *ArtifactPolicyError) Error() string {
	return "solverclient: artifact policy violation: " + e.Msg
}

// ResponseError reports a response that could not be safely decoded
// (malformed JSON or oversized body). It never carries body content.
type ResponseError struct {
	Msg string
}

// Error returns a redacted, body-free description.
func (e *ResponseError) Error() string {
	return "solverclient: response error: " + e.Msg
}
