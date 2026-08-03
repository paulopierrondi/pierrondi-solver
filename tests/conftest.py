"""Shared test fixtures.

The tile-classifier registry in recaptcha_v2_image is module-global: building
a SolverChain on a machine with a vision-capable Ollama registers a real
classifier and leaks it into tests that assert the no-classifier default.
This autouse fixture snapshots and restores the registry around every test.
"""
from __future__ import annotations

import pytest

from pierrondi_solver.strategies import recaptcha_v2_image


@pytest.fixture(autouse=True)
def _preserve_classifier_registry():
    saved = recaptcha_v2_image._CLASSIFIER
    # Start every test from the honest default: no classifier registered.
    recaptcha_v2_image._CLASSIFIER = None
    try:
        yield
    finally:
        recaptcha_v2_image._CLASSIFIER = saved
