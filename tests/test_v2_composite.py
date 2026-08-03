"""Tests for the Ollama vision classifier and the v2 composite strategy.

CI-safe: Ollama HTTP is faked; browser loops are monkeypatched. No network.
"""
from __future__ import annotations

import io
import json

from pierrondi_solver.models import ChallengeType, SolveRequest, StrategyOutcome
from pierrondi_solver.strategies import recaptcha_v2_image
from pierrondi_solver.strategies.recaptcha_v2 import RecaptchaV2Strategy
from pierrondi_solver.strategies.vision_ollama import (
    OllamaVisionClassifier,
    build_default_ollama_classifier,
    ollama_model_available,
    parse_grid_cells,
    parse_indices,
    parse_yes,
    stitch_grid,
)


def req():
    return SolveRequest(type=ChallengeType.recaptcha_v2, sitekey="k", page_url="https://example.com")


# --- parse_indices ---


def test_parse_indices_basic():
    assert parse_indices("0, 4, 7", 9) == [0, 4, 7]


def test_parse_indices_none():
    assert parse_indices("NONE", 9) == []


def test_parse_indices_strict_range_and_dedup():
    assert parse_indices("0, 9, 12, 0", 9) == [0]


def test_parse_indices_prose():
    assert parse_indices("Tiles 2 and 5 match the prompt.", 9) == [2, 5]


# --- availability / factory ---


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ollama_model_available(monkeypatch):
    body = json.dumps({"models": [{"name": "qwen2.5vl:7b"}]}).encode()
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda req, timeout=3: _FakeResp(body)
    )
    assert ollama_model_available("http://127.0.0.1:11434", "qwen2.5vl:7b")


def test_ollama_model_unavailable(monkeypatch):
    def boom(req, timeout=3):
        raise OSError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    assert not ollama_model_available("http://127.0.0.1:11434", "qwen2.5vl:7b")


def test_factory_returns_none_when_unavailable(monkeypatch):
    monkeypatch.setattr(
        "pierrondi_solver.strategies.vision_ollama.ollama_model_available",
        lambda url, model, timeout_s=3: False,
    )
    assert build_default_ollama_classifier({}) is None


def test_factory_opt_out(monkeypatch):
    assert build_default_ollama_classifier({"SOLVER_VISION_OLLAMA": "0"}) is None


def test_factory_builds_when_available(monkeypatch):
    monkeypatch.setattr(
        "pierrondi_solver.strategies.vision_ollama.ollama_model_available",
        lambda url, model, timeout_s=3: True,
    )
    clf = build_default_ollama_classifier({})
    assert isinstance(clf, OllamaVisionClassifier)


# --- classify over fake HTTP ---


def test_classify_sends_images_and_parses(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=120):
        calls.append(json.loads(req.data.decode()))
        return _FakeResp(json.dumps({"message": {"content": "1, 3"}}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    clf = OllamaVisionClassifier(per_tile=False)
    out = clf.classify("crosswalks", [b"png0", b"png1", b"png2", b"png3"])
    assert out == [1, 3]
    msg = calls[0]["messages"][0]
    assert len(msg["images"]) == 4
    assert "crosswalks" in msg["content"]


def test_classify_per_tile_binary(monkeypatch):
    from io import BytesIO

    from PIL import Image

    def png():
        buf = BytesIO()
        Image.new("RGB", (10, 10)).save(buf, format="PNG")
        return buf.getvalue()

    answers = iter(["NO", "YES", "NO", "YES\n"])
    calls = []

    def fake_urlopen(req, timeout=120):
        calls.append(json.loads(req.data.decode()))
        return _FakeResp(json.dumps({"message": {"content": next(answers)}}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    clf = OllamaVisionClassifier(per_tile=True)
    out = clf.classify("cars", [png(), png(), png(), png()])
    assert out == [1, 3]
    assert len(calls) == 4
    assert all(len(c["messages"][0]["images"]) == 1 for c in calls)


def test_parse_yes():
    assert parse_yes("YES") is True
    assert parse_yes("Yes, it matches.") is True
    assert parse_yes("NO") is False
    assert parse_yes("maybe") is False
    assert parse_yes("") is False


def test_parse_grid_cells():
    assert parse_grid_cells("(1,2) (2,3)", 4) == [6, 11]
    assert parse_grid_cells("NONE", 4) == []
    assert parse_grid_cells("(0,0) (9,9) (1,1)", 4) == [0, 5]


def test_stitch_grid_roundtrip():
    from io import BytesIO

    from PIL import Image

    tiles = []
    for i in range(16):
        img = Image.new("RGB", (10, 10), (i * 15, 0, 0))
        buf = BytesIO()
        img.save(buf, format="PNG")
        tiles.append(buf.getvalue())
    photo = stitch_grid(tiles, 4)
    out = Image.open(BytesIO(photo))
    assert out.size == (40, 40)
    # tile 5 lands at (col=1,row=1) -> pixel (15,15) has its red channel
    assert out.getpixel((15, 15))[0] == 5 * 15


def test_classify_grid_mode_for_16_tiles(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=120):
        calls.append(json.loads(req.data.decode()))
        return _FakeResp(json.dumps({"message": {"content": "(1,2) (3,3)"}}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    from io import BytesIO

    from PIL import Image

    tiles = []
    for _ in range(16):
        buf = BytesIO()
        Image.new("RGB", (10, 10)).save(buf, format="PNG")
        tiles.append(buf.getvalue())
    clf = OllamaVisionClassifier(per_tile=True)
    out = clf.classify("buses", tiles)
    assert out == [6, 15]
    assert len(calls) == 1  # one stitched grid call, not 16 per-tile calls


# --- composite strategy ---


class _Stub:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = 0

    def solve(self, request):
        self.calls += 1
        return self.outcome


def _outcome(token="", reason="", strategy="stub"):
    return StrategyOutcome(token=token or None, strategy=strategy, provider="pierrondi", reason=reason)


def test_composite_returns_audio_success_without_image():
    audio = _Stub(_outcome(token="tok-a"))
    image = _Stub(_outcome(token="tok-i"))
    out = RecaptchaV2Strategy(audio=audio, image=image).solve(req())
    assert out.token == "tok-a"
    assert image.calls == 0


def test_composite_falls_back_to_image_on_audio_failure(monkeypatch):
    audio = _Stub(_outcome(reason="audio_unavailable"))
    image = _Stub(_outcome(token="tok-i"))
    monkeypatch.setattr(recaptcha_v2_image, "_CLASSIFIER", object())
    out = RecaptchaV2Strategy(audio=audio, image=image).solve(req())
    assert out.token == "tok-i"


def test_composite_passes_through_skip_markers():
    audio = _Stub(_outcome(reason="deps_missing: playwright"))
    image = _Stub(_outcome(token="tok-i"))
    out = RecaptchaV2Strategy(audio=audio, image=image).solve(req())
    assert out.reason.startswith("deps_missing")
    assert image.calls == 0


def test_composite_honest_when_no_classifier(monkeypatch):
    audio = _Stub(_outcome(reason="audio_unavailable"))
    image = _Stub(_outcome(token="tok-i"))
    monkeypatch.setattr(recaptcha_v2_image, "_CLASSIFIER", None)
    out = RecaptchaV2Strategy(audio=audio, image=image).solve(req())
    assert out.solved is False
    assert out.reason.startswith("not_implemented")
    assert image.calls == 0


def test_composite_reports_both_failures(monkeypatch):
    audio = _Stub(_outcome(reason="audio_unavailable"))
    image = _Stub(_outcome(reason="wrong_tiles"))
    monkeypatch.setattr(recaptcha_v2_image, "_CLASSIFIER", object())
    out = RecaptchaV2Strategy(audio=audio, image=image).solve(req())
    assert out.solved is False
    assert "v2_composite_failed" in out.reason
    assert len(out.reason) <= 400
