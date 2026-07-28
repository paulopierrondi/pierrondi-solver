"""reCAPTCHA v2 image-tile challenge via a pluggable local vision classifier.

Unlike the audio path (which uses the accessibility challenge + Whisper), the
image-tile path needs a vision classifier that, given a grid of tiles and a
challenge prompt ("select all squares with crosswalks"), returns the indices of
matching tiles. That classifier is NOT bundled — the right model depends on the
operator's hardware and accuracy needs (CLIP, YOLO, a fine-tuned MLP, or an
Ollama vision model).

This strategy therefore exposes a ``TileClassifier`` protocol. When a
classifier is registered, the full browser automation loop runs:
open the challenge -> screenshot each tile -> classify -> click matches ->
submit -> read the token. When no classifier is registered, the strategy
reports ``not_implemented`` honestly (it never pretends to solve tiles it
cannot see), and the chain falls through to the audio path or commercial
providers.

Heavy deps (playwright) are optional and imported lazily.
"""
from __future__ import annotations

import time
from typing import Protocol

from ..models import ChallengeType, SolveRequest, StrategyOutcome

# Module-level registry so operators can plug a classifier without forking:
#   from pierrondi_solver.strategies.recaptcha_v2_image import register_classifier
#   register_classifier(MyCLIPClassifier())
_CLASSIFIER = None

CHECKBOX_FRAME_SELECTOR = "iframe[title*='reCAPTCHA'], iframe[src*='anchor']"
BFRAME_URL_MARK = "bframe"
RESPONSE_SELECTOR = "#g-recaptcha-response, textarea[name='g-recaptcha-response']"


class TileClassifier(Protocol):
    """Classifies reCAPTCHA image-tile challenges.

    ``classify(prompt, tile_images)`` receives the human-readable challenge
    prompt (e.g. "crosswalks") and a list of tile images (bytes), and returns
    the 0-based indices of tiles that match the prompt.
    """

    def classify(self, prompt: str, tile_images: list[bytes]) -> list[int]: ...


def register_classifier(classifier: TileClassifier) -> None:
    """Register the global tile classifier used by the image strategy."""
    global _CLASSIFIER
    _CLASSIFIER = classifier


def get_classifier() -> TileClassifier | None:
    return _CLASSIFIER


def _playwright_missing() -> bool:
    try:
        import playwright  # noqa: F401

        return False
    except ImportError:
        return True


class RecaptchaV2ImageStrategy:
    name = "v2_image"
    provider = "pierrondi"

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless

    def supports(self, challenge_type: ChallengeType) -> bool:
        return challenge_type == ChallengeType.recaptcha_v2

    def solve(self, request: SolveRequest) -> StrategyOutcome:
        started = time.monotonic()
        classifier = get_classifier()
        if classifier is None:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason=(
                    "not_implemented: no tile classifier registered "
                    "(register_classifier) — use v2_audio or a commercial provider"
                ),
            )
        if _playwright_missing():
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason="deps_missing: pip install '.[local-solve]' + playwright install chromium",
            )
        try:
            token = self._solve_with_browser(request, classifier)
        except Exception as exc:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason=f"v2_image_failed: {type(exc).__name__}: {exc}"[:400],
            )
        return StrategyOutcome(
            token=token or None,
            strategy=self.name,
            provider=self.provider,
            latency_ms=_elapsed_ms(started),
            cost_usd=0.0,
            reason="" if token else "v2_image_empty_token",
        )

    def _solve_with_browser(self, request: SolveRequest, classifier: TileClassifier) -> str:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.new_context(locale="en-US").new_page()
            try:
                page.goto(request.page_url, wait_until="domcontentloaded",
                          timeout=request.timeout_s * 1000)
                page.wait_for_timeout(1500)
                # Enter the image challenge (click the checkbox to open it).
                page.frame_locator(CHECKBOX_FRAME_SELECTOR).locator(
                    "#recaptcha-anchor").click()
                page.wait_for_timeout(2500)
                bframe = _find_bframe(page)
                if bframe is None:
                    return _read_response(page)  # trusted score; no challenge
                prompt = _extract_prompt(bframe)
                tiles = _extract_tile_images(bframe)
                if not prompt or not tiles:
                    raise RuntimeError("image challenge prompt or tiles not found")
                matches = classifier.classify(prompt, tiles)
                for idx in matches:
                    _click_tile(bframe, idx)
                bframe.locator("#recaptcha-verify-button").click()
                page.wait_for_timeout(2500)
                return _read_response(page)
            finally:
                browser.close()


def _find_bframe(page):
    for frame in page.frames:
        if BFRAME_URL_MARK in frame.url:
            return frame
    return None


def _extract_prompt(bframe) -> str:
    el = bframe.locator(".rc-imageselect-desc-no-canonical, .rc-imageselect-desc")
    if el.count() > 0:
        return (el.first.inner_text() or "").strip()
    return ""


def _extract_tile_images(bframe) -> list[bytes]:
    """Screenshot each tile as PNG bytes. The classifier interprets raw bytes."""
    tiles = bframe.locator(".rc-imageselect-tile")
    images = []
    for i in range(tiles.count()):
        images.append(tiles.nth(i).screenshot())
    return images


def _click_tile(bframe, idx: int) -> None:
    bframe.locator(".rc-imageselect-tile").nth(idx).click()


def _read_response(page) -> str:
    return (
        page.eval_on_selector(
            RESPONSE_SELECTOR, "el => el ? el.value : ''"
        )
        or ""
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
