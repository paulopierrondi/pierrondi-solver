"""Capture a live reCAPTCHA image challenge as a labeled eval fixture.

Opens the official demo, extracts the prompt + tile PNGs, stitches a labeled
grid for the operator to eyeball, and saves tests/fixtures/vision/<slug>.json
plus tile images. The operator (or an agent with vision) fills `expected`
after reviewing <slug>-stitched.png.
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from pierrondi_solver.strategies.recaptcha_v2_image import (
    CHECKBOX_FRAME_SELECTOR,
    _extract_prompt,
    _extract_tile_images,
    _find_bframe,
)
from pierrondi_solver.strategies.vision_ollama import stitch_grid

FIXTURES = Path("tests/fixtures/vision")


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    slug = time.strftime("%Y%m%d-%H%M%S")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_context(locale="en-US").new_page()
        page.goto("https://www.google.com/recaptcha/api2/demo", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        page.frame_locator(CHECKBOX_FRAME_SELECTOR).locator("#recaptcha-anchor").click()
        page.wait_for_timeout(3000)
        bframe = _find_bframe(page)
        if bframe is None:
            print("no challenge this run; retry")
            return 1
        prompt = _extract_prompt(bframe)
        tiles = _extract_tile_images(bframe)
        browser.close()

    grid = math.isqrt(len(tiles))
    (FIXTURES / f"{slug}-stitched.png").write_bytes(stitch_grid(tiles, grid))
    tile_dir = FIXTURES / slug
    tile_dir.mkdir(exist_ok=True)
    for i, img in enumerate(tiles):
        (tile_dir / f"tile-{i:02d}.png").write_bytes(img)
    target = " ".join(prompt.split())
    m = re.search(r"(?:images with|squares with) (?:a |an )?(\w+)", target)
    obj = m.group(1) if m else target
    meta = {
        "prompt": prompt,
        "target": obj,
        "grid": grid,
        "tiles": [f"{slug}/tile-{i:02d}.png" for i in range(len(tiles))],
        "expected": [],
        "note": "fill expected after reviewing the stitched png",
    }
    (FIXTURES / f"{slug}.json").write_text(json.dumps(meta, indent=2))
    print(f"fixture {slug}: {len(tiles)} tiles, target={obj!r}; review {slug}-stitched.png and fill expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
