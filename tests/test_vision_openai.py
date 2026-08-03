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


def test_daily_budget_kill_switch(monkeypatch, tmp_path):
    budget_file = tmp_path / "vision_budget.json"
    budget_file.write_text(json.dumps({
        "date": __import__("time").strftime("%Y-%m-%d"),
        "calls": 200,
        "cost_usd": 1.00,
    }))
    clf = OpenAIVisionClassifier(
        base_url="https://x.test", api_key="k", budget_path=str(budget_file)
    )
    import pytest

    from pierrondi_solver.strategies.vision_openai import VisionBudgetExceeded

    with pytest.raises(VisionBudgetExceeded, match="daily budget"):
        clf._chat("q", [_png()])


def test_per_solve_call_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=120: _FakeResp(
            json.dumps({"choices": [{"message": {"content": "YES"}}]}).encode()
        ),
    )
    clf = OpenAIVisionClassifier(
        base_url="https://x.test",
        api_key="k",
        max_calls_per_solve=2,
        budget_path=str(tmp_path / "b.json"),
    )
    import pytest

    from pierrondi_solver.strategies.vision_openai import VisionBudgetExceeded

    clf._chat("q", [_png()])
    clf._chat("q", [_png()])
    with pytest.raises(VisionBudgetExceeded, match="max_calls_per_solve"):
        clf._chat("q", [_png()])
    clf.begin_solve()
    clf._chat("q", [_png()])  # reset works


def test_cost_accumulates_in_daily_file(tmp_path):
    budget_file = tmp_path / "b.json"

    monkeypatch_called = []
    import pierrondi_solver.strategies.vision_openai as vo

    orig = vo.urllib.request.urlopen
    vo.urllib.request.urlopen = lambda req, timeout=120: _FakeResp(
        json.dumps({"choices": [{"message": {"content": "NONE"}}]}).encode()
    )
    try:
        clf = OpenAIVisionClassifier(
            base_url="https://x.test",
            api_key="k",
            cost_per_call_usd=0.01,
            budget_path=str(budget_file),
        )
        clf._chat("q", [_png()])
        clf._chat("q", [_png()])
    finally:
        vo.urllib.request.urlopen = orig
    data = json.loads(budget_file.read_text())
    assert data["calls"] == 2
    assert abs(data["cost_usd"] - 0.02) < 1e-9
    assert abs(clf.cost_this_solve_usd - 0.02) < 1e-9
    monkeypatch_called  # silence
