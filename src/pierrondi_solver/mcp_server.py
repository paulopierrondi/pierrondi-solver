"""MCP server for pierrondi-solver.

Exposes the solver as Model Context Protocol tools so any MCP-compatible agent
or coder (Codex, Gemini CLI, Antigravity, Claude Code, ...) can detect and solve
challenges without pasting solver code into their own context.

Tools:
    solve_challenge     POST /solve via the canonical client.
    detect_challenge    Extract (type, sitekey) from page HTML.
    get_browser_session List available browser engines + select one.
    service_health      GET /health (status + provider order).
    service_doctor      Full stack audit (deps, keys presence, browser binary).

Transport: stdio by default (``mcp run`` / CLI entry point). The server owns no
state — it delegates to the always-on HTTP service via ``pierrondi_solver.client``.
Secrets never cross the MCP boundary: the client reads env vars directly.

Run:
    pierrondi-solver-mcp            # stdio server (for MCP clients)
    python -m pierrondi_solver.mcp_server
"""
from __future__ import annotations

from . import client
from .browser import BACKENDS, browser_deps_missing

# FastMCP is the high-level server API in the official ``mcp`` SDK.
try:
    from mcp.server.fastmcp import FastMCP
except ImportError as _exc:  # pragma: no cover - import guard for clear errors
    raise SystemExit(
        "mcp SDK not installed. Install with: pip install '.[mcp]'"
    ) from _exc

mcp = FastMCP("pierrondi-solver")


@mcp.tool()
def solve_challenge(
    challenge_type: str,
    page_url: str,
    sitekey: str = "",
    lane: str = "default",
    timeout_s: int = 120,
) -> dict:
    """Solve a CAPTCHA / Cloudflare challenge via the pierrondi-solver service.

    Args:
        challenge_type: One of recaptcha_v2, recaptcha_v3, hcaptcha, turnstile,
            cloudflare. For ``cloudflare`` (interstitial/IUAM) there is no
            sitekey — pass an empty string.
        page_url: The exact page URL where the challenge appears.
        sitekey: The challenge sitekey. Required for non-cloudflare types;
            ignored for cloudflare.
        lane: Routing lane (default "default").
        timeout_s: Max seconds to wait for a solve (5-600).

    Returns:
        {"solved": bool, ...result_or_reason}. On success for cloudflare the
        result includes extra.cookies.cf_clearance and extra.user_agent which
        MUST be reused together from the same IP.
    """
    challenge = client.Challenge(
        type=challenge_type, sitekey=sitekey, page_url=page_url
    )
    return client.solve_verbose(challenge, lane=lane, timeout_s=timeout_s)


@mcp.tool()
def detect_challenge(html: str, page_url: str) -> dict:
    """Detect a known challenge in page HTML and extract its sitekey.

    Useful when an agent has captured page HTML (e.g. from a browser tool) and
    needs to know whether a challenge is present and how to solve it. Returns
    {"challenge": {"type", "sitekey", "page_url"} | null}.

    Args:
        html: The raw page HTML.
        page_url: The page URL the HTML came from.
    """
    challenge = client.detect_challenge(html, page_url)
    if challenge is None:
        return {"challenge": None}
    return {"challenge": challenge.__dict__}


@mcp.tool()
def get_browser_session(engine: str = "chromium") -> dict:
    """List available browser engines or check one engine's readiness.

    The pierrondi-solver local clearance path supports multiple browser engines
    (chromium, firefox, nodriver). This tool reports which are available so an
    agent can request a stronger/stealthier engine when the default fails.

    Args:
        engine: Engine name to inspect (default "chromium"). Pass empty to list
            all registered engines.

    Returns:
        When ``engine`` names a specific engine: {"engine", "available": bool,
        "deps_missing": [...]}.
        When ``engine`` is empty: {"engines": [{name, available, deps_missing}]}.
    """
    if engine:
        return {
            "engine": engine,
            "available": not browser_deps_missing(engine),
            "deps_missing": browser_deps_missing(engine),
        }
    engines = []
    for name in BACKENDS:
        missing = browser_deps_missing(name)
        engines.append({"name": name, "available": not missing, "deps_missing": missing})
    return {"engines": engines}


@mcp.tool()
def service_health() -> dict:
    """Check the pierrondi-solver HTTP service status and configured provider order.

    Returns {"status": "ok"|"down", "providers": [...], ...}. Raises on transport
    errors so the agent can fall back.
    """
    return client.health()


@mcp.tool()
def service_doctor() -> dict:
    """Audit the full solver stack: env var, service health, LaunchAgent,
    local-solve deps, chromium binary, and commercial key presence (never values).

    Returns {"status": "ok"|"degraded", "checks": [...]}.
    """
    checks = client.doctor()
    actionable = [
        r for r in checks
        if not r["check"].startswith("key_") and r["check"] != "proxy_capsolver"
    ]
    status = "ok" if all(r["ok"] for r in actionable) else "degraded"
    return {"status": status, "checks": checks}


def main() -> int:
    """Entry point for the ``pierrondi-solver-mcp`` console script (stdio server)."""
    mcp.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
