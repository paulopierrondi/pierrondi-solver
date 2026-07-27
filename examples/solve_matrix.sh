#!/usr/bin/env bash
# solve_matrix.sh — real-site solve battery across all challenge types.
#
# Usage:
#   ./examples/solve_matrix.sh [base_url]
#
# Defaults to http://127.0.0.1:8791 (the LaunchAgent service). Loads provider
# keys via brain-env-run (central .keys.env); values are never printed.
# Targets are the providers' own official demo pages — authorized test sites.
set -euo pipefail

BASE="${1:-http://127.0.0.1:8791}"
export PIERRONDI_SOLVER_URL="$BASE"

cd "$(dirname "$0")/.."
BIN=".venv/bin/pierrondi-solve"
[[ -x "$BIN" ]] || { echo "missing $BIN (create .venv first)"; exit 1; }

run() { # type sitekey url
  echo "=== $1 @ $3 ==="
  "$BIN" solve --type "$1" --sitekey "$2" --url "$3" --timeout 120 --purpose read_only 2>&1 \
    | .venv/bin/python -c "
import json,sys
raw=sys.stdin.read()
try:
    i=raw.find('{'); d=json.loads(raw[i:raw.rfind('}')+1])
    if d.get('solved'):
        p=d.get('extra',{}).get('artifact_policy',{})
        print('SOLVED provider=%s strategy=%s latency_ms=%s cost_usd=%s token_len=%d consumption=%s'
              % (d.get('provider'),d.get('strategy'),d.get('latency_ms'),d.get('cost_usd'),
                 len(d.get('token','')),p.get('consumption')))
    else:
        print('UNSOLVED reason=%s' % d.get('reason','')[:300])
except Exception:
    print('RAW:', raw[:300])
" || true
}

run recaptcha_v2 "6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-" \
    "https://www.google.com/recaptcha/api2/demo"
run recaptcha_v3 "6LdKlZEpAAAAAAOQjzC2v_d36tWxCl6dWsozdSy9" \
    "https://recaptcha-demo.appspot.com/recaptcha-v3-request-scores.php"
run hcaptcha "a5f74b19-9e45-40e0-b45d-47ff91b7a6c2" \
    "https://accounts.hcaptcha.com/demo"
run turnstile "1x00000000000000000000AA" \
    "https://demo.turnstile.workers.dev/"
