"""hCaptcha via the accessibility AUDIO challenge, transcribed locally.

Flow: stealth Chromium -> set hCaptcha accessibility cookie -> navigate to page
-> open the challenge -> switch to audio -> grab the audio clip -> transcribe
with faster-whisper (100% local, $0) -> submit -> read h-captcha-response.

The hCaptcha accessibility cookie (``hc_accessibility``) enables an audio-based
challenge variant for users with assistive tech. Setting it before navigation
makes the audio path available without a special account.

Heavy deps (playwright, faster-whisper) are optional and imported lazily: when
missing, the strategy reports ``deps_missing`` so the chain falls through to
commercial providers.
"""
from __future__ import annotations

import time

from ..models import ChallengeType, SolveRequest, StrategyOutcome

CHECKBOX_FRAME_SELECTOR = "iframe[title*='hCaptcha'], iframe[src*='hcaptcha']"
CHALLENGE_FRAME_MARK = "hcaptcha-challenge"
AUDIO_BUTTON = "#audio-button"
AUDIO_INPUT = "#audio-response"
SUBMIT_BUTTON = "button[data-cy=submit]"
RESPONSE_SELECTOR = "textarea[name='h-captcha-response'], textarea[name='g-recaptcha-response']"
MAX_ROUNDS = 2

# The public hCaptcha accessibility cookie. When present, hCaptcha exposes the
# audio challenge variant. This is a well-documented public accessibility path,
# not a bypass of authentication or 2FA.
HC_ACCESSIBILITY_COOKIE_URL = "https://accounts.hcaptcha.com/verify_email/"

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


class HCaptchaAudioStrategy:
    name = "hcaptcha_audio"
    provider = "pierrondi"

    def __init__(
        self,
        headless: bool = True,
        whisper_model: str = "base",
        accessibility_cookie: str = "",
    ) -> None:
        self.headless = headless
        self.whisper_model = whisper_model
        self.accessibility_cookie = accessibility_cookie
        self._model = None

    def supports(self, challenge_type: ChallengeType) -> bool:
        return challenge_type == ChallengeType.hcaptcha

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
        if not self.accessibility_cookie:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason=(
                    "deps_missing: hcaptcha local path requires an accessibility "
                    "cookie (HCAPTCHA_ACCESSIBILITY_COOKIE env). See docs/GETTING_KEYS.md."
                ),
            )
        try:
            token = self._solve_with_browser(request)
        except Exception as exc:
            return StrategyOutcome(
                strategy=self.name,
                provider=self.provider,
                latency_ms=_elapsed_ms(started),
                reason=f"hcaptcha_audio_failed: {type(exc).__name__}: {exc}"[:400],
            )
        return StrategyOutcome(
            token=token or None,
            strategy=self.name,
            provider=self.provider,
            latency_ms=_elapsed_ms(started),
            cost_usd=0.0,
            reason="" if token else "hcaptcha_audio_empty_token",
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
            # Seed the accessibility cookie on the hCaptcha domain so the audio
            # challenge variant is available when the widget loads.
            context.add_cookies([
                {
                    "name": "hc_accessibility",
                    "value": self.accessibility_cookie,
                    "domain": ".hcaptcha.com",
                    "path": "/",
                    "httpOnly": False,
                    "secure": True,
                    "sameSite": "None",
                }
            ])
            page = context.new_page()
            try:
                page.goto(
                    request.page_url,
                    wait_until="domcontentloaded",
                    timeout=request.timeout_s * 1000,
                )
                page.wait_for_timeout(1500)
                # Click the hCaptcha checkbox to trigger the challenge.
                page.frame_locator(CHECKBOX_FRAME_SELECTOR).first.locator("#checkbox").click()
                page.wait_for_timeout(2500)
                challenge = _find_challenge_frame(page)
                if challenge is None:
                    # checkbox passed without challenge (trusted score)
                    return _read_response(page)
                for _round in range(MAX_ROUNDS):
                    audio_url = _switch_to_audio_and_extract(challenge)
                    if not audio_url:
                        raise RuntimeError("hcaptcha audio source not found")
                    answer = self._transcribe(audio_url)
                    if not answer:
                        raise RuntimeError("whisper transcription empty")
                    challenge.locator(AUDIO_INPUT).fill(answer)
                    challenge.locator(SUBMIT_BUTTON).click()
                    page.wait_for_timeout(2500)
                    token = _read_response(page)
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

            self._model = WhisperModel(
                self.whisper_model, device="cpu", compute_type="int8"
            )
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as tmp:
            tmp.write(
                httpx.get(
                    audio_url, timeout=30, headers={"User-Agent": _USER_AGENT}
                ).content
            )
            tmp.flush()
            segments, _ = self._model.transcribe(tmp.name, language="en")
            return " ".join(seg.text.strip() for seg in segments).strip()


def _find_challenge_frame(page):
    for frame in page.frames:
        if CHALLENGE_FRAME_MARK in frame.url:
            return frame
    return None


def _switch_to_audio_and_extract(challenge_frame) -> str:
    """Switch the hCaptcha challenge to audio and return the audio clip URL."""
    try:
        challenge_frame.locator(AUDIO_BUTTON).click(timeout=5000)
    except Exception:
        pass  # may already be in audio mode
    challenge_frame.wait_for_timeout(2000)
    audio = challenge_frame.locator("audio[src]")
    if audio.count() > 0:
        return audio.first.get_attribute("src") or ""
    link = challenge_frame.locator("a[download]")
    if link.count() > 0:
        return link.first.get_attribute("href") or ""
    return ""


def _read_response(page) -> str:
    return (
        page.eval_on_selector(
            RESPONSE_SELECTOR, "el => el ? el.value : ''"
        )
        or ""
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
