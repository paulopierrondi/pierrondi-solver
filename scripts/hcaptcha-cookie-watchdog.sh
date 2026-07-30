#!/usr/bin/env bash
# hcaptcha-cookie-watchdog.sh — daily proof of the hCaptcha local audio path.
#
# What it does:
#   1. Probes the live solver with the official hCaptcha demo (local, $0).
#   2. SOLVED  -> quiet OK (journal only).
#   3. Cookie failure -> self-heal: kickstart the solver service once (covers
#      "cookie updated in .keys.env but service not restarted"), re-probe.
#   4. Still failing -> notify Paulo on Slack/outbox with exact remediation
#      (refresh OAuth at dashboard.hcaptcha.com, append to .keys.env).
#
# Notification policy: Slack/outbox + session journal. Never email/Resend.
set -uo pipefail

SOLVER="${PIERRONDI_SOLVER_URL:-http://127.0.0.1:8791}"
DEMO_URL="https://accounts.hcaptcha.com/demo"
DEMO_SITEKEY="a5f74b19-9e45-40e0-b45d-47ff91b7a6c2"
LABEL="com.paulo.pierrondi-solver"
LOG="/Users/paulopierrondi/Projects/pierrondi-solver/data/hcaptcha-watchdog.log"

say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

probe() {
  curl -s --max-time 150 -X POST "$SOLVER/solve" \
    -H 'content-type: application/json' \
    -d "{\"type\":\"hcaptcha\",\"sitekey\":\"$DEMO_SITEKEY\",\"page_url\":\"$DEMO_URL\",\"lane\":\"watchdog\",\"timeout_s\":120,\"purpose\":\"read_only\",\"operation_id\":\"hcaptcha-watchdog\",\"attempt\":1}"
}

notify() {
  local summary="$1"
  say "NOTIFY $summary"
  /Users/paulopierrondi/.local/bin/agent-slack-bridge event \
    --agent-id automation --surface Automation --project-id pierrondi-solver \
    --event-type blocked --status blocked \
    --subject "hCaptcha cookie: acao do Paulo necessaria" \
    --summary "$summary" \
    --risk "hcaptcha local path fora do ar ate o refresh (OAuth Google, 1 clique)" \
    --ref "$LOG" >/dev/null 2>&1 || true
}

say "probe start"
BODY="$(probe)"

if [[ -z "$BODY" ]]; then
  notify "servico solver nao respondeu em $SOLVER (probe hcaptcha). Verificar LaunchAgent $LABEL."
  exit 1
fi

if echo "$BODY" | grep -q '"token"'; then
  say "OK solved"
  exit 0
fi

REASON="$(echo "$BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("reason",""))' 2>/dev/null || echo '')"
say "first probe failed: ${REASON:0:200}"

if echo "$REASON" | grep -qiE "accessibility|empty_token|hcaptcha_audio_failed"; then
  say "self-heal: kickstart $LABEL"
  launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
  sleep 5
  BODY="$(probe)"
  if echo "$BODY" | grep -q '"token"'; then
    say "OK solved after kickstart"
    exit 0
  fi
  REASON="$(echo "$BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("reason",""))' 2>/dev/null || echo '')"
  notify "cookie hCaptcha expirado/invalido. Renovacao: (1) abrir https://dashboard.hcaptcha.com e refazer login Google; (2) DevTools > Application > Cookies > hc_accessibility > copiar Value; (3) atualizar HCAPTCHA_ACCESSIBILITY_COOKIE em /Users/paulopierrondi/Projects/.keys.env; (4) launchctl kickstart -k gui/$(id -u)/$LABEL. Detalhe: ${REASON:0:150}"
  exit 1
fi

say "UNRELATED failure (no notify): ${REASON:0:200}"
exit 0
