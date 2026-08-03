"""Composite reCAPTCHA v2 strategy: audio first, image-tile fallback.

reCAPTCHA v2 offers two challenge variants. The audio path (accessibility
challenge + local Whisper) is cheapest and most reliable, but Google
sometimes withholds it on flagged sessions. This composite keeps the honest
cascade local: try audio, and when it fails, try the image-tile path — which
runs only when a tile classifier is registered (see
``vision_ollama.build_default_ollama_classifier`` for the $0 Ollama wiring).

The composite preserves the codebase's skip semantics: missing deps or no
classifier report ``deps_missing`` / ``not_implemented`` so the chain falls
through to commercial providers without burning breaker budget.
"""
from __future__ import annotations

import time

from ..models import ChallengeType, SolveRequest, StrategyOutcome
from .recaptcha_v2_audio import RecaptchaV2AudioStrategy
from .recaptcha_v2_image import RecaptchaV2ImageStrategy, get_classifier

_SKIP_MARKERS = ("no_api_key", "deps_missing", "not_implemented")


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class RecaptchaV2Strategy:
    name = "v2_composite"
    provider = "pierrondi"

    def __init__(
        self,
        audio: RecaptchaV2AudioStrategy | None = None,
        image: RecaptchaV2ImageStrategy | None = None,
    ) -> None:
        self.audio = audio or RecaptchaV2AudioStrategy()
        self.image = image or RecaptchaV2ImageStrategy()

    def supports(self, challenge_type: ChallengeType) -> bool:
        return challenge_type == ChallengeType.recaptcha_v2

    def solve(self, request: SolveRequest) -> StrategyOutcome:
        started = time.monotonic()

        audio_outcome = self.audio.solve(request)
        if audio_outcome.solved:
            return audio_outcome
        if audio_outcome.reason.startswith(_SKIP_MARKERS):
            return audio_outcome  # real skip: do not mask with image attempt

        # Audio attempted and failed (e.g. audio challenge withheld): try image.
        if get_classifier() is None:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason=f"not_implemented: audio failed ({audio_outcome.reason[:120]}) and no tile classifier registered",
            )
        image_outcome = self.image.solve(request)
        if image_outcome.solved:
            return image_outcome
        return StrategyOutcome(
            strategy=self.name,
            provider=self.provider,
            latency_ms=_elapsed_ms(started),
            reason=(
                f"v2_composite_failed: audio: {audio_outcome.reason[:150]} | "
                f"image: {image_outcome.reason[:150]}"
            )[:400],
        )
