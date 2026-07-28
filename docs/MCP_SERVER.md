# MCP Server

`pierrondi-solver` ships an official **Model Context Protocol (MCP)** server. Any
MCP-compatible agent or coder — Codex, Gemini CLI, Google Antigravity, Claude
Code, or custom clients — can detect and solve challenges as native tools,
without pasting solver code into their own context.

## Install

```bash
pip install -e '.[mcp]'
```

This adds the `pierrondi-solver-mcp` console script and the `mcp` SDK.

The MCP server owns **no state**: it delegates to the always-on HTTP service via
`pierrondi_solver.client`. Make sure the service is running:

```bash
uvicorn pierrondi_solver.main:app --port 8791 --app-dir src
```

## Tools

| Tool | Purpose |
| --- | --- |
| `solve_challenge` | Solve a CAPTCHA / Cloudflare challenge (`type`, `page_url`, `sitekey`, `lane`, `timeout_s`). Returns `{solved, token/​reason, ...}`. Cloudflare results include `extra.cookies.cf_clearance` + `extra.user_agent` (reuse both together). |
| `detect_challenge` | Extract `(type, sitekey)` from page HTML (`html`, `page_url`). Returns `{challenge: {...} \| null}`. |
| `get_browser_session` | List browser engines or check one (`engine`). Returns `{engine, available, deps_missing}` or `{engines: [...]}`. Use to pick a stealthier engine (`nodriver`/`firefox`) when `chromium` fails. |
| `service_health` | `GET /health` — service status + configured provider order. |
| `service_doctor` | Full stack audit: env, service health, deps, browser binary, key presence (never values). |

Secrets never cross the MCP boundary — the client reads env vars directly.

## Client configuration

### Claude Code / Claude Desktop

Add to your MCP client config (e.g. `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "pierrondi-solver": {
      "command": "pierrondi-solver-mcp",
      "env": {
        "PIERRONDI_SOLVER_URL": "http://127.0.0.1:8791"
      }
    }
  }
}
```

### Codex / Gemini CLI / Antigravity

Any client that supports stdio MCP servers points at the same command. Use the
absolute path if the venv is not on `PATH`:

```json
{
  "mcpServers": {
    "pierrondi-solver": {
      "command": "/path/to/venv/bin/pierrondi-solver-mcp"
    }
  }
}
```

### Run manually (stdio)

```bash
pierrondi-solver-mcp
```

The server speaks JSON-RPC over stdio and implements the MCP `initialize` →
`tools/list` → `tools/call` lifecycle.

## Example agent flow

1. Agent captures page HTML via a browser tool.
2. Calls `detect_challenge(html, page_url)` → learns `type=recaptcha_v2, sitekey=...`.
3. Calls `solve_challenge("recaptcha_v2", page_url, sitekey)` → gets a token.
4. Injects the token into the challenge field and continues.

For Cloudflare interstitials (`type=cloudflare`, no sitekey):

1. `solve_challenge("cloudflare", page_url)` → returns
   `extra.cookies.cf_clearance` + `extra.user_agent`.
2. Agent reuses **both** (same UA + same IP) for subsequent requests.

If the default `chromium` engine fails to clear a hardened managed challenge:

1. `get_browser_session("")` → list engines; pick `nodriver` or `firefox`.
2. Restart the service with `SOLVER_BROWSER_ENGINE=nodriver` and retry.

## Responsible use

The MCP server inherits the same policy as the HTTP API: authorized accounts,
properties, QA environments, and automation flows you own or are explicitly
authorized to operate. No login-wall or 2FA bypass, no third-party targets
without authorization.
