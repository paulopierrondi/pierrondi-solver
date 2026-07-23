"""reCAPTCHA v2 via the accessibility AUDIO challenge, transcribed locally.

Flow: stealth Chromium -> click checkbox iframe -> switch to audio challenge
-> grab the MP3 (audio element src, or tdownload link href) -> transcribe
with faster-whisper (100% local, $0) -> submit -> read ``g-recaptcha-response``.

Validated live against https://www.google.com/recaptcha/api2/demo.

Heavy deps (playwright, faster-whisper) are optional and imported lazily:
when missing, the strategy reports ``deps_missing`` so the chain falls
through to commercial providers.
"""
from __future__ import annotations

import time

from ..models import ChallengeType, SolveRequest, StrategyOutcome

CHECKBOX_FRAME_SELECTOR = "iframe[title*='reCAPTCHA'], iframe[src*='anchor']"
BFRAME_URL_MARK = "bframe"
AUDIO_BUTTON = "#recaptcha-audio-button"
AUDIO_INPUT = "#audio-response"
VERIFY_BUTTON = "#recaptcha-verify-button"
RESPONSE_SELECTOR = "#g-recaptcha-response, textarea[name='g-recaptcha-response']"
MAX_ROUNDS = 2

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
_STEALTH_INIT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en', 'pt-BR']});
"""


def _missing_deps() -> list[str]:
    missing = []
    try:
        import playwright  # noqa: F401
    except ImportError:
        missing.append("playwright")
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        missing.append("faster-whisper")
    return missing


class RecaptchaV2AudioStrategy:
    name = "v2_audio"
    provider = "pierrondi"

    def __init__(self, headless: bool = True, whisper_model: str = "base") -> None:
        self.headless = headless
        self.whisper_model = whisper_model
        self._model = None

    def supports(self, challenge_type: ChallengeType) -> bool:
        return challenge_type == ChallengeType.recaptcha_v2

    def solve(self, request: SolveRequest) -> StrategyOutcome:
        started = time.monotonic()
        missing = _missing_deps()
        if missing:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason="deps_missing: pip install '.[local-solve]' + playwright install chromium"
                f" (missing: {', '.join(missing)})",
            )
        try:
            token = self._solve_with_browser(request)
        except Exception as exc:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason=f"v2_audio_failed: {type(exc).__name__}: {exc}"[:400],
            )
        return StrategyOutcome(
            token=token or None,
            strategy=self.name,
            provider=self.provider,
            latency_ms=_elapsed_ms(started),
            cost_usd=0.0,
            reason="" if token else "v2_audio_empty_token",
        )

    def _solve_with_browser(self, request: SolveRequest) -> str:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(user_agent=_USER_AGENT, locale="en-US")
            context.add_init_script(_STEALTH_INIT)
            page = context.new_page()
            try:
                page.goto(request.page_url, wait_until="domcontentloaded",
                          timeout=request.timeout_s * 1000)
                page.wait_for_timeout(1500)
                page.frame_locator(CHECKBOX_FRAME_SELECTOR).locator(
                    "#recaptcha-anchor").click()
                page.wait_for_timeout(2500)
                bframe = _find_bframe(page)
                if bframe is None:
                    # checkbox passed without challenge (trusted score)
                    return page.eval_on_selector(RESPONSE_SELECTOR, "el => el.value") or ""
                bframe.locator(AUDIO_BUTTON).click(timeout=5000)
                page.wait_for_timeout(2500)
                for _round in range(MAX_ROUNDS):
                    audio_url = _extract_audio_url(bframe)
                    if not audio_url:
                        raise RuntimeError("audio challenge source not found")
                    answer = self._transcribe(audio_url)
                    if not answer:
                        raise RuntimeError("whisper transcription empty")
                    bframe.locator(AUDIO_INPUT).fill(answer)
                    bframe.locator(VERIFY_BUTTON).click()
                    page.wait_for_timeout(2500)
                    token = page.eval_on_selector(
                        RESPONSE_SELECTOR, "el => el ? el.value : ''") or ""
                    if token:
                        return token
                return ""
            finally:
                browser.close()

    def _transcribe(self, audio_url: str) -> str:
        import tempfile

        import httpx

        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.whisper_model, device="cpu",
                                       compute_type="int8")
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as tmp:
            tmp.write(httpx.get(audio_url, timeout=30,
                                headers={"User-Agent": _USER_AGENT}).content)
            tmp.flush()
            segments, _ = self._model.transcribe(tmp.name, language="en")
            return " ".join(seg.text.strip() for seg in segments).strip()


def _find_bframe(page):
    for frame in page.frames:
        if BFRAME_URL_MARK in frame.url:
            return frame
    return None


def _extract_audio_url(bframe) -> str:
    # Prefer the <audio> element src; fall back to the download link href.
    audio = bframe.locator("audio[src]")
    if audio.count() > 0:
        return audio.first.get_attribute("src") or ""
    link = bframe.locator(".rc-audiochallenge-tdownload-link")
    if link.count() > 0:
        return link.first.get_attribute("href") or ""
    return ""


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
