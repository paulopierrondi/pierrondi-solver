"""Offline accuracy eval for the Ollama tile classifier.

Runs the classifier over tests/fixtures/vision/*.json fixtures (prompt +
tile images + expected indices) and reports exact-set match plus cell-level
precision/recall. No browser, no external network — Ollama loopback only.

Usage: .venv/bin/python scripts/vision_eval.py [--votes N]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from pierrondi_solver.strategies.vision_ollama import build_default_classifier

FIXTURES = Path("tests/fixtures/vision")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--votes", type=int, default=3)
    args = parser.parse_args()

    clf = build_default_classifier()
    if clf is None:
        print("ollama vision model unavailable")
        return 1
    clf.votes = args.votes

    fixtures = sorted(FIXTURES.glob("*.json"))
    if not fixtures:
        print("no fixtures; run scripts/capture_vision_fixture.py first")
        return 1

    exact = 0
    total_p = total_r = 0.0
    for fx_path in fixtures:
        fx = json.loads(fx_path.read_text())
        expected = set(fx["expected"])
        if not expected and not fx.get("allow_empty", False):
            print(f"{fx_path.stem}: SKIP (expected not filled)")
            continue
        tiles = [(FIXTURES / t).read_bytes() for t in fx["tiles"]]
        t0 = time.monotonic()
        got = set(clf.classify(fx["prompt"], tiles))
        wall = time.monotonic() - t0
        tp = len(got & expected)
        prec = tp / len(got) if got else (1.0 if not expected else 0.0)
        rec = tp / len(expected) if expected else 1.0
        total_p += prec
        total_r += rec
        ok = got == expected
        exact += ok
        print(f"{fx_path.stem}: target={fx['target']!r} expected={sorted(expected)} got={sorted(got)} "
              f"{'EXACT' if ok else 'MISS'} P={prec:.2f} R={rec:.2f} ({wall:.1f}s, votes={args.votes})")
    n = max(1, len([f for f in fixtures if json.loads(f.read_text())["expected"]]))
    print(f"\nexact-set: {exact}  avg P={total_p/n:.2f}  avg R={total_r/n:.2f}  fixtures={len(fixtures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
