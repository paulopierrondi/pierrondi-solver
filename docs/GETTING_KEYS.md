# Where to get the commercial fallback keys + proxy

The solver works **local-only out of the box ($0)**. Commercial providers are the fallback for
flagged IPs, hCaptcha/Turnstile, and heavy Cloudflare. Signup takes ~5 min each.

## 1. CapSolver (recommended primary fallback — best Turnstile/Cloudflare coverage)

1. Go to **https://www.capsolver.com** → Sign up (email or Google).
2. Dashboard → **API Key** (shown on the home dashboard).
3. Add balance: Dashboard → Recharge (pay-as-you-go; ~$6 min via card/crypto).
   Reference pricing: reCAPTCHA v2/v3 ~$1–3/1000, Turnstile ~$0.8–1.5/1000.
4. Store it:

```bash
/Users/paulopierrondi/.local/bin/brain-secret-intake  # choose 'add': name CAPSOLVER_API_KEY, paste the key
# or append the NAME to /Users/paulopierrondi/Projects/.keys.env (value stays out of any repo)
```

## 2. 2Captcha (fallback 2 — oldest, cheapest on simple v2)

1. **https://2captcha.com** → Sign up.
2. Add funds: min ~**$3** (card/crypto) — enough for ~1–2k solves.
3. Dashboard → **API Key** (copy the 32-char key).
4. Store as `TWOCAPTCHA_API_KEY` (same intake flow).

## 3. CapMonster Cloud (fallback 3 — cheapest at volume)

1. **https://capmonster.cloud** → Sign up → Dashboard → API key.
2. Store as `CAPMONSTER_API_KEY`.

## 4. Residential proxy (only needed for CapSolver `AntiCloudflareTask`)

Cloudflare clearance via the commercial path requires a **residential** proxy (datacenter IPs fail).
Budget-friendly options (pay-per-GB, non-expiring traffic):

- **IPRoyal** — https://iproyal.com (residential from ~$1.75/GB, traffic never expires) ← recommended to start
- **Proxy-Cheap** — https://proxy-cheap.com
- Bright Data / Oxylabs / SOAX — premium, if you already have accounts

Buy the smallest package → get credentials in `user:pass@host:port` form → store:

```bash
# name: CAPSOLVER_PROXY   value: http://user:pass@gw.example:12323
/Users/paulopierrondi/.local/bin/brain-secret-intake
```

## 5. Activate (no restart of anything needed beyond the service)

```bash
# after keys are in .keys.env, reload the service with the env:
launchctl kickstart -k gui/$(id -u)/com.paulo.pierrondi-solver
pierrondi-solve doctor   # keys should flip to "set"
```

## Expected monthly cost (Paulo's posting-automation volume)

A few solves/day → **< $1/month**. Commercial only fires when the local tier fails,
so most months cost $0. The circuit breaker + `/metrics` show exactly what was spent.
