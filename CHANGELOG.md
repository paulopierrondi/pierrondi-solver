# Changelog

All notable changes to this project will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses semantic versioning.

## [Unreleased]

### Added

- **Proxy / identity layer** (vetor C): `ProxyConfig`, `IdentityContext`, and
  pluggable `ProxyBackend` (static / rotating / sticky). The clearance harvest
  can route through `SOLVER_PROXY` so `cf_clearance` binds to a controlled IP;
  sticky sessions (`SOLVER_PROXY_ENDPOINT` + `SOLVER_PROXY_STICKY`) keep the
  same IP across harvest + replay. `IdentityContext` makes the (UA + IP +
  cookie) binding invariant explicit.
- **hCaptcha local audio path** (vetor A): `HCaptchaAudioStrategy` solves
  hCaptcha locally via the accessibility cookie → audio challenge →
  `faster-whisper` ($0). Enable with `HCAPTCHA_ACCESSIBILITY_COOKIE`.
- **image-tile pluggable classifier** (vetor A): `RecaptchaV2ImageStrategy` now
  exposes a `TileClassifier` protocol + `register_classifier()`. With a vision
  classifier (CLIP/YOLO/Ollama) registered, the full browser loop runs; without
  one it stays honest (`not_implemented`). No silent fake solves.
- **camoufox backend** (vetor B): hardened anti-detect Firefox clearance
  harvester (`SOLVER_BROWSER_ENGINE=camoufox`). Optional dep
  `pip install '.[camoufox]'`.
- **MCP server** (`pierrondi-solver-mcp`): exposes the solver as Model Context
  Protocol tools (`solve_challenge`, `detect_challenge`, `get_browser_session`,
  `service_health`, `service_doctor`) so any MCP-compatible agent or coder
  (Codex, Gemini CLI, Antigravity, Claude Code) can solve challenges without
  pasting solver code. Optional dep `pip install '.[mcp]'`. See
  [docs/MCP_SERVER.md](docs/MCP_SERVER.md).
- `BrowserBackend` abstraction: Cloudflare clearance no longer hardcoded to
  Chromium. New `browser/` package with `ChromiumBackend` (moved, behavior
  unchanged), `FirefoxBackend` (new engine), and `NodriverBackend` (Chrome via
  CDP, undetected — no webdriver artifacts). Selectable via
  `SOLVER_BROWSER_ENGINE` (`chromium` default, `firefox` / `nodriver` opt-in).
  Clearance responses now include `extra.engine`.
- `PIERRONDI / LABS` brand system and production GitHub assets.
- Premium repository documentation and community health files.
- GitHub Actions test matrix for Python 3.11–3.13.

## [0.1.0] - 2026-07-23

### Added

- FastAPI service with `/solve`, `/health`, and `/metrics`.
- Local reCAPTCHA v2 audio and Cloudflare clearance strategies.
- Commercial fallback cascade for CapSolver, 2Captcha, and CapMonster.
- Per-provider circuit breaker and SQLite cost/success telemetry.
- Python client, CLI, challenge detector, `doctor`, and Claude Code hook.
- 61-test baseline covering API, chain, providers, client, hook, and telemetry.

[Unreleased]: https://github.com/paulopierrondi/pierrondi-solver/compare/f52c57b71a4ab11ce2bded015ecf7b212e2b2d24...HEAD
[0.1.0]: https://github.com/paulopierrondi/pierrondi-solver/commit/f52c57b71a4ab11ce2bded015ecf7b212e2b2d24
