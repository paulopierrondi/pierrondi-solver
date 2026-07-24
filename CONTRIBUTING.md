# Contributing

Thanks for improving `pierrondi-solver`. Contributions should keep the service
small, observable, and safe for authorized automation.

## Development setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

Install the optional local solving stack only when you are working on browser or
audio strategies:

```bash
pip install -e '.[local-solve]'
playwright install chromium
```

## Before opening a pull request

- Add or update tests for behavior changes.
- Run `pytest -q`.
- Keep secret values out of code, fixtures, logs, screenshots, and issues.
- Preserve structured failure reasons; do not replace them with silent fallback.
- Document any new environment variable by name and purpose only.
- Confirm the change is for authorized QA/testing or automation on accounts and
  properties the operator controls.

## Adding a provider or strategy

Implement the existing strategy contract, declare supported challenge types,
return a `StrategyOutcome`, and let `SolverChain` own fallback, breaker, and
telemetry behavior. New providers should not create a parallel routing path.

## Scope boundary

This project does not accept features for mass account creation, credential
abuse, 2FA/login bypass, anti-ban fingerprint evasion, or use against systems
without authorization.
