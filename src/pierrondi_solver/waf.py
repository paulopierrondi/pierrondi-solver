"""Passive WAF / bot-mitigation detection and routing.

Classifies which protection product is present from passive signals only
(HTML body and/or response headers) and maps it to a recommended action.

This is NOT an evasion toolkit (per the canonical decision table in the
Fixture-First Operating Flow): detection never authorizes bypass. Cloudflare
interstitial routes to the solver's own clearance strategy; DataDome,
Queue-it, PerimeterX/HUMAN and Akamai route to ``stop`` — the caller backs
off or hands to a human, it never evades.
"""
from __future__ import annotations

import re
from enum import Enum


class Protection(str, Enum):
    none = "none"
    cloudflare = "cloudflare"
    datadome = "datadome"
    perimeterx = "perimeterx"
    akamai = "akamai"
    queue_it = "queue_it"


class Action(str, Enum):
    proceed = "proceed"
    solver_clearance = "solver_clearance"
    stop = "stop"


_ROUTE = {
    Protection.none: Action.proceed,
    Protection.cloudflare: Action.solver_clearance,
    Protection.datadome: Action.stop,
    Protection.perimeterx: Action.stop,
    Protection.akamai: Action.stop,
    Protection.queue_it: Action.stop,
}

_BODY_SIGNALS: list[tuple[Protection, re.Pattern]] = [
    (
        Protection.cloudflare,
        re.compile(
            r"just a moment|cf_chl|__cf_bm|cf-browser-verification|"
            r"checking your browser|cf-ray|/cdn-cgi/challenge-platform",
            re.I,
        ),
    ),
    (Protection.datadome, re.compile(r"datadome|dd\.js|x-dd-", re.I)),
    (
        Protection.perimeterx,
        re.compile(r"perimeterx|_px\d|px-captcha|human-challenge|px-cloud", re.I),
    ),
    (
        Protection.akamai,
        re.compile(r"_abck|akamai|bm_sz|bot-manager|ak_bmsc", re.I),
    ),
    (
        Protection.queue_it,
        re.compile(r"queue-it|queueit|waiting.?room|softonic.?queue", re.I),
    ),
]

_HEADER_SIGNALS: list[tuple[Protection, str, re.Pattern]] = [
    (Protection.cloudflare, "server", re.compile(r"^cloudflare$", re.I)),
    (Protection.cloudflare, "cf-ray", re.compile(r".+")),
    (Protection.datadome, "x-datadome", re.compile(r".+")),
    (Protection.akamai, "server", re.compile(r"akamaighost", re.I)),
]

# Priority when several products are detected: the interstitial the user
# actually faces wins over weaker signals.
_PRIORITY = [
    Protection.cloudflare,
    Protection.datadome,
    Protection.queue_it,
    Protection.perimeterx,
    Protection.akamai,
    Protection.none,
]


def detect_protection(html: str = "", headers: dict | None = None) -> Protection:
    """Classify the protection product from passive signals.

    ``html`` is the response body (may be empty); ``headers`` an optional
    case-insensitive mapping of response headers. Returns the highest
    priority Protection found, or Protection.none.
    """
    found: set[Protection] = set()
    for protection, pattern in _BODY_SIGNALS:
        if html and pattern.search(html):
            found.add(protection)
    if headers:
        lowered = {str(k).lower(): str(v) for k, v in headers.items()}
        for protection, header, pattern in _HEADER_SIGNALS:
            value = lowered.get(header)
            if value is not None and pattern.search(value):
                found.add(protection)
    for protection in _PRIORITY:
        if protection in found:
            return protection
    return Protection.none


def recommended_action(protection: Protection) -> Action:
    """Map a detected protection to the canonical routing action."""
    return _ROUTE[protection]


def assess(html: str = "", headers: dict | None = None) -> dict:
    """Convenience: detection + routing in one structured dict."""
    protection = detect_protection(html, headers)
    return {
        "protection": protection.value,
        "action": recommended_action(protection).value,
    }
