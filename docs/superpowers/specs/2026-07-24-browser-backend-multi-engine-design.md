# BrowserBackend — Multi-Engine Browser Abstraction (Design)

**Date:** 2026-07-24
**Vector:** B — Multi-engine + stealth
**Slice:** 1 — Extract `BrowserBackend` interface; add Firefox engine
**Registry id:** `pierrondi-solver`

## Problem

`pierrondi-solver` is locked to a **single browser engine**: Chromium via Playwright.
The Cloudflare clearance strategy instantiates Playwright Chromium directly inside
`_harvest_clearance` (`src/pierrondi_solver/strategies/cloudflare_clearance.py`).

"Full access to any browser" is impossible while engine selection is hardcoded
into a strategy. Adding Firefox, WebKit, or anti-detect engines (camoufox /
nodriver / patchright) requires rewriting the strategy each time.

## Goal

Break the engine lock-in with a **reversible, minimal extraction**:

1. Introduce a `BrowserBackend` interface that the Cloudflare strategy depends on.
2. Move Chromium into `ChromiumBackend` with zero behavior change.
3. Add a `FirefoxBackend` as the second engine.
4. Select the backend via config (`SOLVER_BROWSER_ENGINE`).
5. Prove the contract with tests (no live network in CI).

This is slice 1 of vector B. Subsequent slices add more engines, session pools,
and stealth profiles on top of the same interface.

## Non-Goals (this slice)

- hCaptcha / Turnstile local strategies (vector A).
- Proxy / residential identity layer (vector C).
- MCP server + agent adapters (vector D).
- camoufox / nodriver / patchright (later slice of vector B).
- Persistent session/cookie pool (later slice of vector B).

## Architecture

### Current (engine hardcoded in strategy)

```
CloudflareClearanceStrategy
  └─ _harvest_clearance() → pw.chromium.launch(headless=False, args=...)
```

### Proposed (backend injected)

```
CloudflareClearanceStrategy(backend: BrowserBackend)
  └─ backend.harvest_clearance(url, timeout_s, opts) → HarvestedContext
```

New package layout:

```
src/pierrondi_solver/browser/
├── __init__.py          # get_browser(name) factory + BACKENDS registry
├── base.py              # BrowserBackend Protocol + BrowserOpts + HarvestedContext
├── chromium.py          # ChromiumBackend    (moved from cloudflare_clearance.py)
├── firefox.py           # FirefoxBackend     (NEW — Playwright Firefox)
└── nodriver_backend.py  # NodriverBackend    (NEW — Chrome via CDP, undetected)
```

## Components

### `browser/base.py`

```python
@dataclass
class BrowserOpts:
    user_agent: str
    viewport: dict
    locale: str
    headless: bool = False

@dataclass
class HarvestedContext:
    clearance: str
    user_agent: str
    cookies: dict
    engine: str            # telemetry: which engine produced this clearance

class BrowserBackend(Protocol):
    name: str
    def deps_missing(self) -> list[str]: ...
    def harvest_clearance(self, page_url: str, timeout_s: int, opts: BrowserOpts) -> HarvestedContext: ...
```

`deps_missing()` returns `[]` when ready, or a list of pip-install hints. A non-empty
list makes the chain skip the backend without burning breaker budget — the same
pattern the codebase already uses for `_playwright_missing`.

### `browser/chromium.py`

Behavior identical to today's `_harvest_clearance`: launch args
(`--disable-blink-features=AutomationControlled`, `--no-first-run`,
`--no-default-browser-check`), stealth init script, fixed UA/viewport/locale,
poll for `cf_clearance` until timeout. Raises on failure.

### `browser/firefox.py`

Same harvest algorithm, `pw.firefox.launch(...)` instead of `pw.chromium`.
No `add_init_script` stealth injection (Firefox fingerprint differs from Chrome;
the Chrome-oriented script targets `window.chrome` / `navigator.webdriver`
Chrome-isms and is not applicable). This is the first diversification of the
fingerprint surface.

### `browser/nodriver_backend.py`

Chrome via CDP, **no webdriver**. `nodriver` (successor of
undetected-chromedriver) drives a real Chrome binary through the Chrome DevTools
Protocol directly, so it never exposes `navigator.webdriver = true` or the
webdriver process artifacts that Playwright/Selenium leak. Materially harder for
managed challenges to fingerprint. Async-first; the synchronous
`harvest_clearance` bridge runs the coroutine on a dedicated event loop.
Cookies are read via `cdp.network.get_cookies()`. Optional dep
(`pip install '.[nodriver]'`); missing → `deps_missing`.

### `browser/__init__.py`

```python
def get_browser(name: str) -> BrowserBackend: ...
def browser_deps_missing(name: str) -> list[str]: ...
BACKENDS = {"chromium": ChromiumBackend, "firefox": FirefoxBackend}
```

### `strategies/cloudflare_clearance.py` (refactor)

- Constructor: `def __init__(self, backend: BrowserBackend | None = None)` →
  defaults to `ChromiumBackend()` (backward compatible).
- `solve()` calls `backend.deps_missing()` first → `deps_missing` reason on miss.
- `_harvest_clearance` removed; delegates to `backend.harvest_clearance(...)`.

### `config.py`

New field + env var:

```python
browser_engine: str = "chromium"   # env SOLVER_BROWSER_ENGINE
```

`load_config` reads it; `SolverChain.__init__` selects `get_browser(config.browser_engine)`
when building the Cloudflare strategy.

## Data Flow

```
POST /solve {type: cloudflare, page_url, timeout_s}
  → SolverChain.solve()
    → CloudflareClearanceStrategy(backend)
      → backend.deps_missing()
          []? continue
          non-empty? → StrategyOutcome(reason="deps_missing: <engine>: <hints>")
                       (chain skips, no breaker burn)
      → backend.harvest_clearance(page_url, timeout_s, opts)
          → HarvestedContext(clearance, user_agent, cookies, engine)
      → StrategyOutcome(
            token=clearance,
            extra={user_agent, cookies, usage, engine}
        )
  → SolveResult / 422 UnsolvedError
```

`BrowserOpts` defaults reproduce today's hardcoded values exactly, so Chromium
fingerprint and behavior are unchanged.

## Error Handling

| Condition | Reason string | Breaker effect |
| --- | --- | --- |
| Engine deps missing | `deps_missing: <engine>: <hints>` | skip, no burn (existing pattern) |
| Harvest exception | `cf_clearance_failed: <ExcType>: <msg>` | record + burn (existing pattern) |
| Timeout, no cookie | `cf_clearance_not_granted_within_timeout` | record + burn (existing pattern) |
| Unknown engine name | `deps_missing: unknown_engine: <name>` | skip, no burn |

All reason strings keep the prefixes the chain already matches
(`deps_missing`, `cf_clearance_failed`) so existing skip/record logic is unchanged.

## Testing

CI-safe (no network, no real browser launch) — implemented in `tests/test_browser.py`:

- `test_registry_has_chromium_and_firefox`, `test_get_browser_returns_instances`,
  `test_get_browser_is_case_insensitive_and_trimmed` — registry/factory.
- `test_get_browser_unknown_raises`, `test_browser_deps_missing_unknown_engine_reports_hint`
  — unknown engine handling.
- `test_chromium_backend_name`, `test_chromium_missing_deps_reports` (monkeypatch).
- `test_firefox_backend_name`, `test_firefox_missing_deps_reports` (monkeypatch).
- `test_strategy_accepts_injected_backend_and_solves` — fake backend returns
  `HarvestedContext`, asserts solved + `extra.engine` + cookies.
- `test_strategy_reports_deps_missing_from_backend` — deps miss surfaces as reason.
- `test_strategy_translates_harvest_exception` — exception → `cf_clearance_failed`.
- `test_strategy_reports_timeout_when_no_clearance` — empty clearance → timeout reason.
- `test_default_backend_is_chromium` — backward compatibility.
- `test_build_cloudflare_strategy_uses_engine` / `test_build_cloudflare_strategy_unknown_engine_reports_deps_missing`.
- `test_strategy_supports_only_cloudflare`.

Existing tests (`test_cloudflare.py`, `test_strategies.py`) must remain green —
this is an extraction, not a contract change.

Live Firefox/Chromium solves use the `live` marker and stay outside CI, matching
the existing convention.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `SOLVER_BROWSER_ENGINE` | `chromium` | Select clearance browser backend (`chromium`, `firefox`) |

## Backward Compatibility

- Default engine = chromium → identical behavior to today.
- `CloudflareClearanceStrategy()` with no args → Chromium (existing tests pass).
- No API contract change (`POST /solve` unchanged); `extra.engine` is additive.

## Success Criteria

- `pytest -q` green with the new tests added and all existing tests unchanged.
- `SOLVER_BROWSER_ENGINE=firefox` produces a `FirefoxBackend` in the chain.
- `SOLVER_BROWSER_ENGINE=chromium` (default) reproduces today's behavior.
- No behavior change for callers that do not set the new env var.

## Future Slices (out of scope here)

- camoufox / nodriver / patchright backends (same interface).
- `SessionPool`: persistent profiles + cookie jar per host/lane.
- `StealthProfile`: consistent fingerprint generator across engines.
- Local hCaptcha / Turnstile strategies reusing `BrowserBackend`.
