#!/usr/bin/env bash
# Restart only the FastAPI origin inside the all-model SNP guest.
set -euo pipefail

ROOT=${VINFER_ROOT:-$HOME/verified-inference}
TOKEN_FILE=${VINFER_ORIGIN_TOKEN_FILE:-$HOME/.config/vinfer/origin-token}
RELAY_TOKEN_FILE=${VINFER_RECEIPT_RELAY_TOKEN_FILE:-$HOME/.config/vinfer/receipt-relay-token}

test -c /dev/sev-guest
for file in "$TOKEN_FILE" "$RELAY_TOKEN_FILE"; do
  test -s "$file"
  test "$(stat -c %a "$file")" = 600
done
cd "$ROOT"
export PATH="$HOME/.local/bin:$PATH"
mapfile -t ports < <(uv run python - <<'PY'
from server import registry

print(*(model.port for model in registry.load().values() if model.servable), sep="\n")
PY
)
for port in "${ports[@]}"; do
  curl -sf --max-time 3 "http://127.0.0.1:$port/health" >/dev/null
done
curl -sf --max-time 3 http://10.0.2.2:8480/healthz >/dev/null

pkill -f 'uvicorn server.main:app' 2>/dev/null || true
for _ in $(seq 1 30); do
  ! ss -ltn 'sport = :8477' | grep -q LISTEN && break
  sleep 0.2
done

VINFER_SEV_MODE=snp \
VINFER_REQUIRE_AUTH=1 \
VINFER_AUTH_TOKEN="$(cat "$TOKEN_FILE")" \
VINFER_AUTH_COOKIE_PATH=/ \
VINFER_AUTH_SECURE_COOKIE=1 \
VINFER_RECEIPT_RELAY_URL=http://10.0.2.2:8480 \
VINFER_RECEIPT_RELAY_TOKEN_FILE="$RELAY_TOKEN_FILE" \
  nohup uv run uvicorn server.main:app --host 0.0.0.0 --port 8477 \
  > "$HOME/logs/vinfer/origin.log" 2>&1 &

for _ in $(seq 1 120); do
  curl -sf --max-time 2 http://127.0.0.1:8477/healthz && exit 0
  sleep 1
done
echo "attested origin did not become healthy" >&2
exit 2
