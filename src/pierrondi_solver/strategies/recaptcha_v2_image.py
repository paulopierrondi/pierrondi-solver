"""reCAPTCHA v2 image-tile challenge via a local vision model (Ollama).

Status: honest stub. The interface and chain wiring are ready; the tile
classification loop is pending a validated vision model. Until then this
strategy always returns unsolved with a clear reason so the chain falls
through to commercial providers. See README backlog.
"""
from __future__ import annotations

import time

from ..models import ChallengeType, SolveRequest, StrategyOutcome


class RecaptchaV2ImageStrategy:
    name = "v2_image"
    provider = "pierrondi"

    def supports(self, challenge_type: ChallengeType) -> bool:
        return challenge_type == ChallengeType.recaptcha_v2

    def solve(self, request: SolveRequest) -> StrategyOutcome:
        return StrategyOutcome(
            strategy=self.name,
            provider=self.provider,
            latency_ms=0,
            reason="not_implemented: vision-tile classification pending (use v2_audio first)",
        )
