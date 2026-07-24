# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| `0.1.x` | Yes |
| Older snapshots | No |

## Reporting a vulnerability

Please use
[GitHub's private vulnerability reporting flow](https://github.com/paulopierrondi/pierrondi-solver/security/advisories/new).
Do not open a public issue for vulnerabilities that expose tokens, provider
credentials, private URLs, or a practical abuse path.

Include:

- the affected version or commit;
- a minimal reproduction;
- expected and observed behavior;
- security impact;
- any safe mitigation you already tested.

Never include live API keys, cookies, tokens, credentials, or private customer
data. Redacted examples are sufficient.

## Security properties

- Provider keys are environment-only.
- Telemetry stores token fingerprints, not raw tokens.
- The service binds locally by default in the documented setup.
- Login walls and 2FA are explicitly outside policy.
- Operators are responsible for target-site authorization and Terms of Service.
