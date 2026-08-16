"""Request/response contracts for the solver API."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class ChallengeType(str, Enum):
    recaptcha_v2 = "recaptcha_v2"
    recaptcha_v3 = "recaptcha_v3"
    hcaptcha = "hcaptcha"
    turnstile = "turnstile"
    cloudflare = "cloudflare"  # interstitial/IUAM: solved via cf_clearance cookie, not a field token


class SolvePurpose(str, Enum):
    """Semantic stage where the returned artifact will be consumed."""

    generic = "generic"
    authentication = "authentication"
    read_only = "read_only"
    state_change = "state_change"


class SolveRequest(BaseModel):
    type: ChallengeType
    sitekey: str = ""  # cloudflare interstitial has no sitekey
    page_url: str = Field(min_length=8)
    lane: str = "default"
    timeout_s: int = Field(default=120, ge=5, le=600)
    purpose: SolvePurpose = SolvePurpose.generic
    operation_id: str = Field(
        default="",
        max_length=80,
        pattern=r"^(?:|[A-Za-z0-9][A-Za-z0-9._:-]{0,79})$",
        description=(
            "Opaque non-secret correlation ID; raw value is not stored in telemetry."
        ),
    )
    attempt: int = Field(default=1, ge=1, le=1000)

    @model_validator(mode="after")
    def _sitekey_required_unless_cloudflare(self):
        if self.type != ChallengeType.cloudflare and not self.sitekey:
            raise ValueError("sitekey is required for non-cloudflare challenges")
        return self

    def artifact_policy(self) -> dict:
        """Tell callers how narrowly to consume the returned artifact."""
        session_bound = self.type == ChallengeType.cloudflare
        return {
            "purpose": self.purpose.value,
            "operation_id": self.operation_id,
            "attempt": self.attempt,
            "consumption": "session_bound" if session_bound else "single_use",
            "must_not_reuse_across_purposes": not session_bound,
        }


class SolveResult(BaseModel):
    token: str
    strategy: str
    provider: str
    latency_ms: int
    cost_usd: float = 0.0
    # For cloudflare interstitial: {"user_agent": ..., "cookies": {"cf_clearance": ...}}
    extra: dict = Field(default_factory=dict)


class UnsolvedError(BaseModel):
    error: str = "unsolved"
    reason: str
    fallback_recommended: bool = True
    attempts: list[str] = Field(default_factory=list)


class StrategyOutcome(BaseModel):
    """Internal result of a single strategy/provider attempt."""

    token: Optional[str] = None
    strategy: str = "unknown"
    provider: str = "unknown"
    latency_ms: int = 0
    cost_usd: float = 0.0
    reason: str = ""
    extra: dict = Field(default_factory=dict)

    @property
    def solved(self) -> bool:
        return bool(self.token)
