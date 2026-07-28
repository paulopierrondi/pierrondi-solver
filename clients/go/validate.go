package solverclient

import (
	"regexp"
)

// operationIDPattern mirrors the Python SolveRequest pattern:
// empty, or [A-Za-z0-9][A-Za-z0-9._:-]{0,79}.
var operationIDPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$`)

const (
	minTimeoutS   = 5
	maxTimeoutS   = 600
	minAttempt    = 1
	maxAttempt    = 1000
	minPageURLLen = 8
)

// Validate enforces locally the same invariants the Python API enforces with
// Pydantic, so invalid requests fail before any network I/O. Returned errors
// never echo the offending values.
func (r SolveRequest) Validate() error {
	if !r.Type.known() {
		return &ValidationError{Field: "type", Msg: "unknown challenge type"}
	}
	if r.Type != ChallengeCloudflare && r.Sitekey == "" {
		return &ValidationError{Field: "sitekey", Msg: "required for non-cloudflare challenges"}
	}
	if len(r.PageURL) < minPageURLLen {
		return &ValidationError{Field: "page_url", Msg: "must be at least 8 characters"}
	}
	if r.TimeoutS < minTimeoutS || r.TimeoutS > maxTimeoutS {
		return &ValidationError{Field: "timeout_s", Msg: "must be between 5 and 600"}
	}
	if r.Attempt < minAttempt || r.Attempt > maxAttempt {
		return &ValidationError{Field: "attempt", Msg: "must be between 1 and 1000"}
	}
	if !r.Purpose.known() {
		return &ValidationError{Field: "purpose", Msg: "unknown purpose"}
	}
	if r.OperationID != "" && !operationIDPattern.MatchString(r.OperationID) {
		return &ValidationError{Field: "operation_id", Msg: "must match [A-Za-z0-9][A-Za-z0-9._:-]{0,79}"}
	}
	return nil
}
