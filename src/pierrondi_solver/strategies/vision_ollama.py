"""Local vision classifier for reCAPTCHA image tiles via Ollama ($0).

Sends the challenge tiles to a local Ollama vision model (default
``qwen2.5vl:7b``) over loopback HTTP — no external network, no API keys.
When Ollama or the model is unreachable, the factory returns ``None`` and the
image strategy stays honestly ``not_implemented`` (the chain then falls
through to commercial providers).
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.request

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_VISION_MODEL = "qwen2.5vl:7b"

_INSTRUCTION = (
    "These images are tiles from one CAPTCHA grid, in order: image 1 is tile 0, "
    "image 2 is tile 1, and so on. The challenge prompt is: {prompt!r}. "
    "Reply with ONLY the 0-based indices of tiles that match the prompt, "
    "comma-separated (e.g. '0, 4, 7'), or the word NONE if no tile matches."
)


class OllamaVisionClassifier:
    """TileClassifier backed by a local Ollama vision model.

    ``per_tile=True`` (default) classifies each tile with an independent
    binary question — materially more accurate on small noisy tiles than one
    batched 9-image call, at the cost of N sequential requests.
    """

    def __init__(self, model: str = DEFAULT_VISION_MODEL, base_url: str = DEFAULT_OLLAMA_URL, timeout_s: int = 120, per_tile: bool = True, votes: int = 3) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.per_tile = per_tile
        # Grid answers come from `votes` independent inferences; a cell must
        # win the majority. Vision models are stochastic — consensus is the
        # cheapest real accuracy lever.
        self.votes = max(1, votes)

    def classify(self, prompt: str, tile_images: list[bytes]) -> list[int]:
        # Sliced single-photo grids (4x4) need full context: an object often
        # spans several tiles and each slice alone is unreadable. Stitch the
        # tiles back into the grid photo and ask for grid cells instead.
        if len(tile_images) == 16 and self.per_tile:
            return self._classify_grid(prompt, tile_images, grid=4)
        if self.per_tile:
            return [
                idx
                for idx, img in enumerate(tile_images)
                if self._classify_one(prompt, img)
            ]
        return self._classify_batch(prompt, tile_images)

    def _classify_grid(self, prompt: str, tile_images: list[bytes], grid: int = 4) -> list[int]:
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

    def _chat(self, content: str, images: list[bytes]) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": content,
                    "images": [base64.b64encode(i).decode("ascii") for i in images],
                }
            ],
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return (data.get("message", {}) or {}).get("content", "") or ""

    def _classify_one(self, prompt: str, image: bytes) -> bool:
        question = (
            f"This is one tile from a CAPTCHA grid. The challenge prompt is: "
            f"{prompt!r}. Does this tile show the target, even partially? "
            "Be generous with vehicles and large objects. Answer YES or NO only."
        )
        answer = self._chat(question, [upscale_png(image)])
        return parse_yes(answer)

    def _classify_batch(self, prompt: str, tile_images: list[bytes]) -> list[int]:
        return parse_indices(self._chat(_INSTRUCTION.format(prompt=prompt), tile_images), len(tile_images))


def upscale_png(png: bytes, factor: int = 4) -> bytes:
    """Upscale a small tile so the vision model can actually see it."""
    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(png))
    if img.width >= 400:
        return png
    out = img.resize((img.width * factor, img.height * factor), Image.LANCZOS)
    buf = BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def label_grid(png: bytes, grid: int) -> bytes:
    """Draw grid lines + (row,col) labels on the stitched photo.

    Vision models localize far better when the grid is explicit on the image.
    """
    from io import BytesIO

    from PIL import Image, ImageDraw

    img = Image.open(BytesIO(png)).convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.width // grid, img.height // grid
    for i in range(1, grid):
        draw.line([(i * w, 0), (i * w, img.height)], fill=(183, 255, 42), width=3)
        draw.line([(0, i * h), (img.width, i * h)], fill=(183, 255, 42), width=3)
    for r in range(grid):
        for c in range(grid):
            draw.rectangle([c * w + 4, r * h + 4, c * w + 52, r * h + 22], fill=(5, 7, 6))
            draw.text((c * w + 8, r * h + 6), f"({r},{c})", fill=(183, 255, 42))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def stitch_grid(tile_images: list[bytes], grid: int) -> bytes:
    """Reassemble row-major tile PNGs into the original grid photo (PNG bytes)."""
    from io import BytesIO

    from PIL import Image

    tiles = [Image.open(BytesIO(img)) for img in tile_images]
    w, h = tiles[0].size
    photo = Image.new("RGB", (w * grid, h * grid))
    for idx, tile in enumerate(tiles):
        photo.paste(tile, ((idx % grid) * w, (idx // grid) * h))
    buf = BytesIO()
    photo.save(buf, format="PNG")
    return buf.getvalue()


def parse_grid_cells(text: str, grid: int) -> list[int]:
    """Parse '(row,col) (row,col)' answers into flat tile indices."""
    if "NONE" in text.upper() and "(" not in text:
        return []
    out = []
    for row, col in re.findall(r"\((\d)\s*,\s*(\d)\)", text):
        r, c = int(row), int(col)
        if 0 <= r < grid and 0 <= c < grid:
            idx = r * grid + c
            if idx not in out:
                out.append(idx)
    return out


def majority_cells(answers: list[str], grid: int, votes: int) -> list[int]:
    """Cell must appear in more than half of the inference answers."""
    threshold = votes // 2 + 1
    counts: dict[int, int] = {}
    for answer in answers:
        for idx in parse_grid_cells(answer, grid):
            counts[idx] = counts.get(idx, 0) + 1
    return sorted(idx for idx, n in counts.items() if n >= threshold)


def parse_yes(text: str) -> bool:
    """Interpret a binary YES/NO model answer; ambiguity defaults to NO."""
    head = text.strip().upper()[:12]
    return head.startswith("YES")


def parse_indices(text: str, tile_count: int) -> list[int]:
    """Extract 0-based tile indices from the model reply; strict on range."""
    if "NONE" in text.upper() and not re.search(r"\d", text):
        return []
    found = []
    for token in re.findall(r"\d+", text):
        idx = int(token)
        if 0 <= idx < tile_count and idx not in found:
            found.append(idx)
    return found


def ollama_model_available(base_url: str, model: str, timeout_s: int = 3) -> bool:
    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        names = {m.get("name", "") for m in data.get("models", [])}
        return model in names or model.split(":")[0] in {n.split(":")[0] for n in names}
    except Exception:
        return False


def build_default_classifier(env: dict | None = None):
    """Provider-agnostic vision classifier factory.

    ``SOLVER_VISION_PROVIDER=openai`` selects the hosted OpenAI-compatible
    backend (vision_openai); anything else keeps the local Ollama default.
    Returns None when the selected backend is unavailable.
    """
    env = env if env is not None else os.environ
    if env.get("SOLVER_VISION_PROVIDER", "ollama").strip().lower() == "openai":
        from .vision_openai import build_openai_classifier

        return build_openai_classifier(env)
    return build_default_ollama_classifier(env)


def build_default_ollama_classifier(env: dict | None = None) -> OllamaVisionClassifier | None:
    """Return a ready classifier, or None when Ollama/model is unavailable.

    Env: ``SOLVER_OLLAMA_URL`` (default loopback), ``SOLVER_OLLAMA_VISION_MODEL``
    (default ``qwen2.5vl:7b``). Set ``SOLVER_VISION_OLLAMA=0`` to opt out.
    """
    env = env if env is not None else os.environ
    if env.get("SOLVER_VISION_OLLAMA", "1").strip().lower() in ("0", "false", "no"):
        return None
    base_url = env.get("SOLVER_OLLAMA_URL", DEFAULT_OLLAMA_URL)
    model = env.get("SOLVER_OLLAMA_VISION_MODEL", DEFAULT_VISION_MODEL)
    if not ollama_model_available(base_url, model):
        return None
    return OllamaVisionClassifier(model=model, base_url=base_url)
