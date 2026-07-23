"""reCAPTCHA v3 is score-based, NOT challenge-response: there is no token to
"solve" client-side. The site calls grecaptcha.execute() itself and scores
behavior (0.0-1.0). What actually helps:

  1. Clean, stable browser fingerprint (persistent profile, real UA).
  2. Residential IP reputation (datacenter IPs score low).
  3. Human-like pacing on the page before execute() is called.
  4. Warm session cookies on the site's domain.

This strategy therefore NEVER returns a token. It reports the mitigation
guidance so the caller can (a) fix its browsing posture, or (b) let the
chain try commercial providers, which maintain high-score infrastructure.
"""
from __future__ import annotations

from ..models import ChallengeType, SolveRequest, StrategyOutcome

V3_MITIGATION = (
    "v3_is_score_based: no token to solve; improve fingerprint/IP/pacing, "
    "or let the page fall back to a v2 challenge and resubmit as recaptcha_v2"
)


class RecaptchaV3Strategy:
    name = "v3_score_mitigation"
    provider = "pierrondi"

    def supports(self, challenge_type: ChallengeType) -> bool:
        return challenge_type == ChallengeType.recaptcha_v3

    def solve(self, request: SolveRequest) -> StrategyOutcome:
        return StrategyOutcome(
            strategy=self.name,
            provider=self.provider,
            latency_ms=0,
            reason=V3_MITIGATION,
        )
