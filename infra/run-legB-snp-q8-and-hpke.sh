#!/usr/bin/env bash
# Run after 8b-q8 is staged and the SNP guest is restored. Rebuilds the complete
# matched four-model SNP matrix and measures every HPKE cell with a signed
# HPKE-key binding. Each concurrency cell is isolated by the harness runner.
set -euo pipefail

cd "$HOME/verified-inference"
export PATH="$HOME/.local/bin:$PATH"
test -c /dev/sev-guest
if [ ! -r /dev/sev-guest ] || [ ! -w /dev/sev-guest ]; then
  sudo chgrp "$(id -gn)" /dev/sev-guest
  sudo chmod 0660 /dev/sev-guest
fi
test -r /dev/sev-guest -a -w /dev/sev-guest
if ! mountpoint -q /mnt/models; then
  sudo mount -o ro /dev/vdc /mnt/models
fi
OUT_SINGLE="runs/legB-snp-single-full.jsonl"
OUT_CONC="runs/legB-snp-concurrency-isolated.jsonl"
OUT_HPKE="runs/legB-snp-hpke-bound.jsonl"
LOGS="$HOME/logs/legB-snp-q8"
mkdir -p "$LOGS" runs
RUNTIME_PID=

stop_runtimes() {
  if [ -n "$RUNTIME_PID" ]; then
    kill "$RUNTIME_PID" 2>/dev/null || true
    wait "$RUNTIME_PID" 2>/dev/null || true
    RUNTIME_PID=
  fi
}
trap stop_runtimes EXIT

start_runtimes() {
  local threads="$1"
  stop_runtimes
  VINFER_BITNETCPP_SERVER=/mnt/models/bitnet-bin/llama-server \
  VINFER_LLAMACPP_SERVER=/mnt/models/llamacpp-bin/llama-server \
    nohup uv run python -m server.serve_models \
      --models bitnet-2b,8b-q4,8b-q8,70b-q4 --threads "$threads" \
      --context-cap 16384 --parallel 8 >"$LOGS/models-t${threads}.log" 2>&1 &
  RUNTIME_PID=$!
  uv run python -m server.serve_models \
    --models bitnet-2b,8b-q4,8b-q8,70b-q4 --status --startup-timeout 720
}

restart_vinfer() {
  pkill -f 'uvicorn server.main:app' 2>/dev/null || true
  sleep 2
  VINFER_SEV_MODE=snp \
  VINFER_AVAILABLE_MODELS=bitnet-2b,8b-q4,8b-q8,70b-q4 \
    nohup uv run uvicorn server.main:app --host 0.0.0.0 --port 8477 \
    >"$LOGS/vinfer.log" 2>&1 &
  for _ in $(seq 1 60); do
    curl -sf --max-time 2 http://127.0.0.1:8477/healthz >/dev/null && break
    sleep 1
  done
  curl -sf http://127.0.0.1:8477/v1/attestation >/tmp/q8-attestation.json
  uv run python - <<'PY'
import json
from cli.attest_verify import verify_attestation
d = json.load(open('/tmp/q8-attestation.json'))
assert sorted(x['id'] for x in d['registry']) == ['70b-q4', '8b-q4', '8b-q8', 'bitnet-2b']
assert d['hpke_binding_signature_b64']
v = verify_attestation(d)
assert v.trusted, v.reason
print('four-model VMPL0 SNP attestation + signed HPKE binding verified')
PY
}

for threads in 16 32; do
  start_runtimes "$threads"
  if [ "$threads" = 16 ]; then restart_vinfer; fi
  matrix="/tmp/legB-single-t${threads}.json"
  python3 - "$threads" "$matrix" <<'PY'
import json, sys
t, path = int(sys.argv[1]), sys.argv[2]
json.dump({"n_per_cell": 10, "grid": {
  "leg": ["B"],
  "model": ["bitnet-2b", "8b-q4", "8b-q8", "70b-q4"],
  "prompt_tokens": [128, 1024],
  "output_tokens": [128], "threads": [t], "concurrency": [1],
  "input_mode": ["tls"], "numa_policy": ["guest-single-numa"]}}, open(path, 'w'))
PY
  VINFER_URL=http://127.0.0.1:8477 uv run python -m harness.runner "$matrix" "$OUT_SINGLE"
done

python3 - <<'PY'
import json
json.dump({"n_per_cell": 10, "grid": {
  "leg": ["B"], "model": ["bitnet-2b", "8b-q4", "8b-q8", "70b-q4"],
  "prompt_tokens": [128, 1024],
  "output_tokens": [128], "threads": [32], "concurrency": [4, 8],
  "input_mode": ["tls"], "numa_policy": ["guest-single-numa"]}},
  open('/tmp/legB-concurrency-isolated.json', 'w'))
json.dump({"n_per_cell": 10, "grid": {
  "leg": ["B"], "model": ["bitnet-2b", "8b-q4", "8b-q8", "70b-q4"],
  "prompt_tokens": [128], "output_tokens": [128], "threads": [32],
  "concurrency": [1], "input_mode": ["hpke"],
  "numa_policy": ["guest-single-numa"]}}, open('/tmp/legB-hpke-bound.json', 'w'))
PY
VINFER_URL=http://127.0.0.1:8477 uv run python -m harness.runner \
  /tmp/legB-concurrency-isolated.json "$OUT_CONC"
VINFER_URL=http://127.0.0.1:8477 uv run python -m harness.runner \
  /tmp/legB-hpke-bound.json "$OUT_HPKE"

echo "single-stream rows: $(wc -l < "$OUT_SINGLE"); isolated concurrency: $(wc -l < "$OUT_CONC"); bound HPKE: $(wc -l < "$OUT_HPKE")"
