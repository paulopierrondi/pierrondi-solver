"""Tests for the OpenAI-compatible vision classifier. No network — HTTP faked."""
from __future__ import annotations

import io
import json

from pierrondi_solver.strategies.vision_openai import (
    OpenAIVisionClassifier,
    build_openai_classifier,
)


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _png():
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (10, 10)).save(buf, format="PNG")
    return buf.getvalue()


def test_chat_posts_openai_shape(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=120):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["payload"] = json.loads(req.data.decode())
        return _FakeResp(json.dumps({"choices": [{"message": {"content": "(1,2)"}}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    clf = OpenAIVisionClassifier(model="gemini-2.5-flash", base_url="https://example.test/v1", api_key="k", votes=1)
    out = clf._chat("q", [_png()])
    assert out == "(1,2)"
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["auth"] == "Bearer k"
    parts = captured["payload"]["messages"][0]["content"]
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert captured["payload"]["temperature"] == 0


def test_classify_grid_uses_consensus(monkeypatch):
    answers = iter(["(1,2) (3,3)", "(1,2)", "(3,3)"])

    def fake_urlopen(req, timeout=120):
        return _FakeResp(json.dumps({"choices": [{"message": {"content": next(answers)}}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    clf = OpenAIVisionClassifier(base_url="https://example.test", api_key="k", votes=3)
    out = clf.classify("buses", [_png()] * 16)
    assert out == [6, 15]


def test_classify_one_parse(monkeypatch):
    def fake_urlopen(req, timeout=120):
        return _FakeResp(json.dumps({"choices": [{"message": {"content": "YES"}}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    clf = OpenAIVisionClassifier(base_url="https://example.test", api_key="k")
    assert clf._classify_one("cars", _png()) is True


def test_factory_requires_url_and_key():
    assert build_openai_classifier({}) is None
    assert build_openai_classifier({"SOLVER_VISION_BASE_URL": "https://x.test"}) is None
    clf = build_openai_classifier(
        {"SOLVER_VISION_BASE_URL": "https://x.test", "SOLVER_VISION_API_KEY": "k", "SOLVER_VISION_MODEL": "m"}
    )
    assert clf is not None and clf.model == "m"


def test_factory_falls_back_to_known_keys():
    clf = build_openai_classifier(
        {"SOLVER_VISION_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY": "g"}
    )
    assert clf is not None and clf.api_key == "g"
    clf = build_openai_classifier({"SOLVER_VISION_BASE_URL": "https://api.moonshot.ai/v1", "KIMI_API_KEY": "k"})
    assert clf is not None and clf.api_key == "k"
