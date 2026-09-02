"""Hosted vision classifiers via any OpenAI-compatible API (OpenAI, Gemini
openai-compat endpoint, Moonshot/Kimi, etc.).

Same TileClassifier contract as the Ollama backend: per-tile binary mode for
independent 3x3 tiles, stitched labeled-grid mode for sliced photos. Consensus
voting applies to grid mode only; per-tile calls are single-shot to cap
hosted-API cost. Provider is selected by env:

    SOLVER_VISION_PROVIDER   "ollama" (default) | "openai"
    SOLVER_VISION_BASE_URL   e.g. https://generativelanguage.googleapis.com/v1beta/openai
    SOLVER_VISION_MODEL      e.g. gemini-2.5-flash | gpt-4o-mini | moonshot-v1-8k-vision-preview
    SOLVER_VISION_API_KEY    loaded via brain-env-run / .keys.env, never logged

Note: DeepSeek's hosted API is text-only (no vision endpoint), so it is not
a supported backend here; its open-source VL models would run via a local
runtime instead.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
from dataclasses import dataclass

from .vision_ollama import (
    label_grid,
    majority_cells,
    parse_yes,
    stitch_grid,
    upscale_png,
)

DEFAULT_MODEL = "gemini-2.5-flash"


class VisionBudgetExceeded(RuntimeError):
    """Raised when the hosted vision budget or per-solve call cap is hit."""


_BUDGET_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "data", "vision_budget.json"
)


def _load_budget(path: str) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
        if data.get("date") == time.strftime("%Y-%m-%d"):
            return data
    except Exception:
        pass
    return {"date": time.strftime("%Y-%m-%d"), "calls": 0, "cost_usd": 0.0}


def _save_budget(path: str, data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception:
        pass  # budget persistence must never break a solve


@dataclass
class VisionBudget:
    """Cost caps for a hosted vision backend (see OpenAIVisionClassifier).

    ``max_calls_per_solve`` default 108 = 3 challenges x 4 rounds x 9
    single-shot per-tile calls (worst case on the 3x3 path; the 4x4 grid
    path uses only 3 x 4 x 3 = 36 voted calls). A lower cap aborts mid-solve
    with ``budget_exceeded`` as soon as a challenge retry happens.
    """

    cost_per_call_usd: float = 0.005  # conservative for flash-class models
    daily_budget_usd: float = 1.00
    max_calls_per_solve: int = 108
    path: str = _BUDGET_FILE

    @classmethod
    def from_env(cls, env: dict | None = None) -> "VisionBudget":
        env = env if env is not None else os.environ
        return cls(
            cost_per_call_usd=float(env.get("SOLVER_VISION_COST_PER_CALL_USD", "0.005")),
            daily_budget_usd=float(env.get("SOLVER_VISION_DAILY_BUDGET_USD", "1.00")),
            max_calls_per_solve=int(env.get("SOLVER_VISION_MAX_CALLS_PER_SOLVE", "108")),
        )


class OpenAIVisionClassifier:
    """TileClassifier backed by an OpenAI-compatible chat completions API.

    Cost control (hosted APIs are metered) is grouped in ``VisionBudget``:
    ``cost_per_call_usd`` is charged per API call into a daily counter at
    ``data/vision_budget.json``; crossing ``daily_budget_usd`` or
    ``max_calls_per_solve`` raises VisionBudgetExceeded and the strategy
    reports an honest ``budget_exceeded`` reason. Env overrides:
    ``SOLVER_VISION_COST_PER_CALL_USD``, ``SOLVER_VISION_DAILY_BUDGET_USD``,
    ``SOLVER_VISION_MAX_CALLS_PER_SOLVE``.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = "",
        api_key: str = "",
        timeout_s: int = 120,
        votes: int = 3,
        budget: VisionBudget | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.votes = max(1, votes)
        budget = budget or VisionBudget.from_env()
        self.cost_per_call_usd = budget.cost_per_call_usd
        self.daily_budget_usd = budget.daily_budget_usd
        self.max_calls_per_solve = budget.max_calls_per_solve
        self.budget_path = budget.path
        self.calls_this_solve = 0
        self.cost_this_solve_usd = 0.0

    def begin_solve(self) -> None:
        """Reset the per-solve counters. Strategies call this at solve start."""
        self.calls_this_solve = 0
        self.cost_this_solve_usd = 0.0

    def classify(self, prompt: str, tile_images: list[bytes]) -> list[int]:
        # 16 tiles = one photo sliced into a 4x4 grid: stitch and ask for grid
        # cells, since objects span slices and each slice alone is unreadable.
        # 9 independent 3x3 tiles classify better one-by-one; per-tile calls
        # stay single-shot (no voting) to cap hosted-API cost.
        if len(tile_images) == 16:
            return self._classify_grid(prompt, tile_images, grid=4)
        return [
            idx
            for idx, img in enumerate(tile_images)
            if self._classify_one(prompt, img)
        ]

    def _chat(self, content: str, images: list[bytes]) -> str:
        self.calls_this_solve += 1
        if self.calls_this_solve > self.max_calls_per_solve:
            raise VisionBudgetExceeded(
                f"max_calls_per_solve {self.max_calls_per_solve} exceeded"
            )
        budget = _load_budget(self.budget_path)
        if budget["cost_usd"] + self.cost_per_call_usd > self.daily_budget_usd:
            raise VisionBudgetExceeded(
                f"daily budget ${self.daily_budget_usd:.2f} exceeded"
            )
        budget["calls"] += 1
        budget["cost_usd"] = round(budget["cost_usd"] + self.cost_per_call_usd, 6)
        _save_budget(self.budget_path, budget)
        self.cost_this_solve_usd = round(
            self.cost_this_solve_usd + self.cost_per_call_usd, 6
        )
        parts = [{"type": "text", "text": content}]
        for img in images:
            b64 = base64.b64encode(img).decode("ascii")
            parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": parts}],
            "temperature": 0,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

    def _classify_grid(self, prompt: str, tile_images: list[bytes], grid: int) -> list[int]:
        photo = label_grid(upscale_png(stitch_grid(tile_images, grid), factor=2), grid)
        question = (
            f"This photo is divided into a {grid}x{grid} grid "
            f"(rows and columns numbered 0 to {grid - 1}, row first). "
            f"The challenge prompt is: {prompt!r}. "
            "Which grid cells contain any part of the target? "
            "Be generous with vehicles and large objects. "
            "Reply ONLY with the cells as (row,col) pairs separated by spaces, "
            "e.g. '(1,2) (2,3)', or the word NONE."
        )
        answers = [self._chat(question, [photo]) for _ in range(self.votes)]
        return majority_cells(answers, grid, self.votes)

    def _classify_one(self, prompt: str, image: bytes) -> bool:
        question = (
            f"This is one tile from a CAPTCHA grid. The challenge prompt is: "
            f"{prompt!r}. Does this tile show the target, even partially? "
            "Be generous with vehicles and large objects. Answer YES or NO only."
        )
        return parse_yes(self._chat(question, [upscale_png(image)]))


def build_openai_classifier(env: dict | None = None):
    """Build the hosted classifier from env, or None when not configured.

    Falls back to well-known key names for convenience; values stay in env.
    """
    env = env if env is not None else os.environ
    base_url = env.get("SOLVER_VISION_BASE_URL", "").strip()
    model = env.get("SOLVER_VISION_MODEL", "").strip()
    api_key = env.get("SOLVER_VISION_API_KEY", "").strip()
    if not api_key:
        if "generativelanguage" in base_url:
            api_key = env.get("GEMINI_API_KEY", "")
        elif "moonshot" in base_url:
            api_key = env.get("KIMI_API_KEY", "") or env.get("MOONSHOT_API_KEY", "")
        else:
            api_key = env.get("OPENAI_API_KEY", "")
    if not base_url or not api_key:
        return None
    return OpenAIVisionClassifier(
        model=model or DEFAULT_MODEL,
        base_url=base_url,
        api_key=api_key,
    )
