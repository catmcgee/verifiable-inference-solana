#!/usr/bin/env bash
# Run inside the cloned 32-vCPU plain twin. Mirrors the feasible TLS portion of
# the matched SNP matrix and writes a distinct raw artifact.
set -euo pipefail

cd "$HOME/verified-inference"
export PATH="$HOME/.local/bin:$PATH"

if [ -c /dev/sev-guest ]; then
  echo "FATAL: /dev/sev-guest exists; refusing to label this twin SEV-off" >&2
  exit 2
fi
if ! mountpoint -q /mnt/models; then
  sudo mount -o ro /dev/vdc /mnt/models
fi
OUT="runs/legA-snp-twin-full.jsonl"
LOGS="$HOME/logs/legA-snp-twin"
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
  VINFER_SEV_MODE=off \
  VINFER_AVAILABLE_MODELS=bitnet-2b,8b-q4,8b-q8,70b-q4 \
    nohup uv run uvicorn server.main:app --host 127.0.0.1 --port 8477 \
    >"$LOGS/vinfer.log" 2>&1 &
  for _ in $(seq 1 60); do
    curl -sf --max-time 2 http://127.0.0.1:8477/healthz >/dev/null && break
    sleep 1
  done
  test "$(curl -sf http://127.0.0.1:8477/v1/attestation | python3 -c 'import json,sys; print(json.load(sys.stdin)["grade"])')" = none
}

run_matrix() {
  VINFER_URL=http://127.0.0.1:8477 uv run python -m harness.runner "$1" "$OUT"
}

for threads in 16 32; do
  echo "=== plain twin threads=${threads} ==="
  start_runtimes "$threads"
  if [ "$threads" = 16 ]; then restart_vinfer; fi
  matrix="/tmp/legA-snp-twin-t${threads}.json"
  python3 - "$threads" "$matrix" <<'PY'
import json, sys
t, path = int(sys.argv[1]), sys.argv[2]
json.dump({"n_per_cell": 10, "grid": {
  "leg": ["A"], "model": ["bitnet-2b", "8b-q4", "8b-q8", "70b-q4"],
  "prompt_tokens": [128, 1024], "output_tokens": [128],
  "threads": [t], "concurrency": [1], "input_mode": ["tls"],
  "numa_policy": ["guest-single-numa"]}}, open(path, "w"))
PY
  run_matrix "$matrix"
done

python3 - <<'PY'
import json
json.dump({"n_per_cell": 10, "grid": {
  "leg": ["A"], "model": ["bitnet-2b", "8b-q4", "8b-q8", "70b-q4"],
  "prompt_tokens": [128, 1024], "output_tokens": [128], "threads": [32],
  "concurrency": [4, 8], "input_mode": ["tls"],
  "numa_policy": ["guest-single-numa"]}}, open('/tmp/legA-snp-twin-concurrency.json', 'w'))
PY
run_matrix /tmp/legA-snp-twin-concurrency.json

echo "Leg A plain twin complete: $(wc -l < "$OUT") rows -> $OUT"
