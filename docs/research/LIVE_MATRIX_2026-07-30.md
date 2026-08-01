# Live matrix — 2026-07-30 (public receipts)

One run of `examples/solve_matrix.sh` against the local service, official
provider demo pages only, local strategies only, $0 provider cost:

```
=== recaptcha_v2 @ https://www.google.com/recaptcha/api2/demo ===
SOLVED provider=pierrondi strategy=v2_audio latency_ms=14114 cost_usd=0.0 consumption=single_use
=== recaptcha_v3 @ https://recaptcha-demo.appspot.com/recaptcha-v3-request-scores.php ===
SOLVED provider=pierrondi strategy=v3_execute latency_ms=4451 cost_usd=0.0 consumption=single_use
=== hcaptcha @ https://accounts.hcaptcha.com/demo ===
SOLVED provider=pierrondi strategy=hcaptcha_audio latency_ms=7161 cost_usd=0.0 consumption=single_use
=== turnstile @ https://demo.turnstile.workers.dev/ ===
SOLVED provider=pierrondi strategy=turnstile_harvest latency_ms=4515 cost_usd=0.0 consumption=single_use
```

Cloudflare clearance has its own validated harvest path (session-bound;
cookie + user agent + IP as one identity).

These are single-run latencies from one machine on a residential BR
connection — they are receipts that the paths work, not benchmarks.
Sitekeys are the providers' public test keys. Raw tokens are never stored;
telemetry keeps a 12-char hash.
