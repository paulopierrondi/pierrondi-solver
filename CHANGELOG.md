# Changelog

All notable changes to this project will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses semantic versioning.

## [Unreleased]

### Added

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
