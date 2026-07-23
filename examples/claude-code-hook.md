# Claude Code auto-solve hook

Makes Claude Code resolve CAPTCHA/Cloudflare challenges **silently** whenever a browser
tool's output contains one — instead of stopping to ask you.

## Install

Add to `~/.claude/settings.json` (merge with existing hooks):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "mcp__scrapling__.*|WebFetch|mcp__.*browser.*|mcp__playwright.*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/pierrondi-solver/hooks/captcha_posttool_hook.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

## How it works

1. After any matched tool runs, the hook scans the output for challenge markers
   (`g-recaptcha`, `cf-turnstile`, `just a moment`, `cf_chl_`, `hcaptcha`, ...).
2. If found, it injects `additionalContext` telling the agent to solve via the local
   service — with the **sitekey already extracted** — and to only escalate to the human
   on exhausted cascade, login walls or 2FA.
3. No markers → zero output, zero noise. It never blocks.

The agent then calls:

```
POST $PIERRONDI_SOLVER_URL/solve {"type": "...", "sitekey": "...", "page_url": "..."}
```

and continues the task with the returned token (or `cf_clearance` cookie + UA for Cloudflare).

## Manual pattern (any agent, no hooks)

Paste this rule into your agent's global instructions:

> On CAPTCHA/Cloudflare: do NOT ask the user. Solve via `$PIERRONDI_SOLVER_URL/solve`
> (health at `/health`, audit with `pierrondi-solve doctor`). For Cloudflare interstitials
> use `type="cloudflare"` and reuse `extra.cookies.cf_clearance` + `extra.user_agent`
> from the same IP. Escalate only on 422 after the full cascade, login wall or 2FA.
