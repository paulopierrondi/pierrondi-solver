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


class SolveRequest(BaseModel):
    type: ChallengeType
    sitekey: str = ""  # cloudflare interstitial has no sitekey
    page_url: str = Field(min_length=8)
    lane: str = "default"
    timeout_s: int = Field(default=120, ge=5, le=600)

    @model_validator(mode="after")
    def _sitekey_required_unless_cloudflare(self):
        if self.type != ChallengeType.cloudflare and not self.sitekey:
            raise ValueError("sitekey is required for non-cloudflare challenges")
        return self


class SolveResult(BaseModel):
    token: str
    strategy: str
    provider: str
    latency_ms: int
    cost_usd: float = 0.0
    # For cloudflare interstitial: {"user_agent": ..., "cookies": {"cf_clearance": ...}}
    extra: dict = {}


class UnsolvedError(BaseModel):
    error: str = "unsolved"
    reason: str
    fallback_recommended: bool = True
    attempts: list[str] = []


class StrategyOutcome(BaseModel):
    """Internal result of a single strategy/provider attempt."""

    token: Optional[str] = None
    strategy: str = "unknown"
    provider: str = "unknown"
    latency_ms: int = 0
    cost_usd: float = 0.0
    reason: str = ""
    extra: dict = {}

    @property
    def solved(self) -> bool:
        return bool(self.token)
