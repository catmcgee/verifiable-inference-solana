#!/usr/bin/env bash
# Start a generated pay gateway on loopback. Caddy owns public TLS.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SPEC=${VINFER_PAY_SPEC:-$ROOT/payskill/inference.yaml}
TOKEN_FILE=${VINFER_ORIGIN_TOKEN_FILE:-$HOME/.config/vinfer/origin-token}
PUBLIC_URL=${VINFER_PAY_PUBLIC_URL:?set VINFER_PAY_PUBLIC_URL to the paid HTTPS origin}
BIND=${VINFER_PAY_BIND:-127.0.0.1:1402}
PID_FILE=${VINFER_PAY_PID_FILE:-$HOME/.local/state/vinfer/pay-gateway.pid}
LOG_FILE=${VINFER_PAY_LOG_FILE:-$HOME/logs/vinfer/pay-gateway.log}

command -v pay >/dev/null
test -s "$SPEC"
test -s "$TOKEN_FILE"
test "$(stat -c %a "$TOKEN_FILE")" = "600" || {
  echo "$TOKEN_FILE must have mode 600" >&2
  exit 2
}

mkdir -p "$(dirname "$PID_FILE")" "$(dirname "$LOG_FILE")"
if test -s "$PID_FILE" && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "pay gateway is already running (pid $(cat "$PID_FILE"))" >&2
  exit 2
fi

VINFER_ORIGIN_TOKEN="$(cat "$TOKEN_FILE")" \
  nohup pay server start "$SPEC" \
    --bind "$BIND" \
    --openapi "$ROOT/payskill/openapi.json" \
    --public-url "$PUBLIC_URL" \
    >"$LOG_FILE" 2>&1 &
pid=$!
printf '%s\n' "$pid" >"$PID_FILE"

base="http://$BIND"
for _ in $(seq 1 120); do
  curl -sf --max-time 2 "$base/v1/models" >/dev/null && break
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "pay gateway exited; inspect $LOG_FILE" >&2
    exit 1
  fi
  sleep 1
done

headers=$(mktemp)
trap 'rm -f "$headers"' EXIT
status=$(curl -sS -o /dev/null -D "$headers" -w '%{http_code}' \
  -H 'content-type: application/json' \
  -d '{"model":"bitnet-2b","messages":[{"role":"user","content":"payment check"}],"max_tokens":1}' \
  "$base/v1/chat/completions")
test "$status" = "402"
grep -qi '^payment-required:' "$headers"
echo "pay gateway ready at $BIND; public URL $PUBLIC_URL"
