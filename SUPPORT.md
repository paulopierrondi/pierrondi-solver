# Support

Use GitHub Issues for:

- reproducible bugs;
- installation failures;
- provider contract regressions;
- feature proposals with a clear authorized-use case.

Before filing an issue, run:

```bash
pierrondi-solve doctor
pytest -q
```

Share the redacted `doctor` output, Python version, operating system, and the
smallest safe reproduction. Never share API keys, raw tokens, cookies,
credentialed URLs, or private HTML.

Security-sensitive reports belong in
[private vulnerability reporting](https://github.com/paulopierrondi/pierrondi-solver/security/advisories/new).
