#!/usr/bin/env bash
# Start the measured SNP origin behind browser-session/bearer auth.
# The external pay gateway supplies the bearer token only after x402 payment.
set -euo pipefail

cd "$HOME/verified-inference"
export PATH="$HOME/.local/bin:$PATH"

test -c /dev/sev-guest
if [ ! -r /dev/sev-guest ] || [ ! -w /dev/sev-guest ]; then
  sudo chgrp "$(id -gn)" /dev/sev-guest
  sudo chmod 0660 /dev/sev-guest
fi
test -r /dev/sev-guest -a -w /dev/sev-guest
TOKEN_FILE="$HOME/.config/vinfer/origin-token"
test -s "$TOKEN_FILE" || {
  echo "missing $TOKEN_FILE" >&2
  exit 2
}
test "$(stat -c %a "$TOKEN_FILE")" = "600" || {
  echo "$TOKEN_FILE must have mode 600" >&2
  exit 2
}

pkill -f 'uvicorn server.main:app' 2>/dev/null || true
sleep 2
mkdir -p "$HOME/logs/vinfer" "$HOME/.local/state/vinfer"

VINFER_SEV_MODE=snp \
VINFER_REQUIRE_AUTH=1 \
VINFER_AUTH_TOKEN="$(cat "$TOKEN_FILE")" \
VINFER_AUTH_COOKIE_PATH=/vinfer \
VINFER_AUTH_SECURE_COOKIE=1 \
  nohup uv run uvicorn server.main:app --host 0.0.0.0 --port 8477 \
  >"$HOME/logs/vinfer/origin.log" 2>&1 &

for _ in $(seq 1 90); do
  curl -sf --max-time 2 http://127.0.0.1:8477/healthz >/dev/null && break
  sleep 1
done
curl -sf http://127.0.0.1:8477/healthz >/tmp/vinfer-final-health.json
curl -sf http://127.0.0.1:8477/v1/attestation >/tmp/vinfer-final-attestation.json
status=$(curl -sS -o /dev/null -w '%{http_code}' \
  -H 'content-type: application/json' \
  -d '{"model":"bitnet-2b","messages":[{"role":"user","content":"auth check"}],"max_tokens":1}' \
  http://127.0.0.1:8477/v1/chat/completions)
test "$status" = "401"
uv run python - <<'PY'
import json
from cli.attest_verify import verify_attestation
from server import registry

health = json.load(open('/tmp/vinfer-final-health.json'))
assert health['available_models'], health
attestation = json.load(open('/tmp/vinfer-final-attestation.json'))
assert attestation['active_models'] == health['available_models']
expected = sorted(model.id for model in registry.load().values() if model.servable)
assert sorted(row['id'] for row in attestation['registry']) == expected
verdict = verify_attestation(attestation)
assert verdict.trusted, verdict.reason
print(f"authenticated origin ready: {len(health['available_models'])} models; "
      "VMPL0 SNP report; signed HPKE binding")
PY
