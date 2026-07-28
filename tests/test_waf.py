"""Tests for the passive WAF detector/router (waf.py). Fixture-only, no network."""
from __future__ import annotations

from pierrondi_solver.waf import (
    Action,
    Protection,
    assess,
    detect_protection,
    recommended_action,
)

CF_HTML = "<html><title>Just a moment...</title><p>Checking your browser before accessing the site.</p></html>"
DD_HTML = '<html><script src="https://ct.datadome.co/js/dd.js"></script><p>geo.captcha-delivery.com</p></html>'
PX_HTML = '<html><script src="https://collector-pxu6j0fk8c.px-cloud.net/api/v2/collector"></script></html>'
AKAMAI_HTML = '<html><script>var _abck = "x";</script><p>AkamaiGHost</p></html>'
QUEUE_HTML = '<html><script src="https://static.queue-it.net/queueit.min.js"></script><p>waiting room</p></html>'
PLAIN_HTML = "<html><title>Welcome</title><p>job posting content</p></html>"


def test_plain_page_is_none():
    assert detect_protection(PLAIN_HTML) is Protection.none


def test_cloudflare_interstitial_by_body():
    assert detect_protection(CF_HTML) is Protection.cloudflare


def test_cloudflare_by_headers():
    assert detect_protection("", {"Server": "cloudflare"}) is Protection.cloudflare
    assert detect_protection("", {"CF-RAY": "8f123-GRU"}) is Protection.cloudflare


def test_datadome_by_body_and_header():
    assert detect_protection(DD_HTML) is Protection.datadome
    assert detect_protection("", {"X-DataDome": "protected"}) is Protection.datadome


def test_perimeterx_akamai_queueit():
    assert detect_protection(PX_HTML) is Protection.perimeterx
    assert detect_protection(AKAMAI_HTML) is Protection.akamai
    assert detect_protection("", {"Server": "AkamaiGHost"}) is Protection.akamai
    assert detect_protection(QUEUE_HTML) is Protection.queue_it


def test_headers_are_case_insensitive():
    assert detect_protection("", {"sErVeR": "Cloudflare"}) is Protection.cloudflare


def test_priority_cloudflare_wins_over_weaker_signals():
    assert detect_protection(CF_HTML + AKAMAI_HTML) is Protection.cloudflare
    assert detect_protection(DD_HTML + PLAIN_HTML) is Protection.datadome


def test_routing_matches_canonical_decision_table():
    assert recommended_action(Protection.none) is Action.proceed
    assert recommended_action(Protection.cloudflare) is Action.solver_clearance
    for p in (Protection.datadome, Protection.perimeterx, Protection.akamai, Protection.queue_it):
        assert recommended_action(p) is Action.stop


def test_assess_returns_structured_dict():
    assert assess(DD_HTML) == {"protection": "datadome", "action": "stop"}
    assert assess(PLAIN_HTML) == {"protection": "none", "action": "proceed"}
    assert assess(CF_HTML) == {"protection": "cloudflare", "action": "solver_clearance"}
