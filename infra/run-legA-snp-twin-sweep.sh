#!/usr/bin/env bash
# Run inside the cloned 32-vCPU plain twin. Mirrors the feasible TLS portion of
# run-legB-snp-sweep.sh and writes a distinct raw artifact.
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
test -f /mnt/models/models/llama-3.1-8b-instruct-Q8_0.gguf

OUT="runs/legA-snp-twin-full.jsonl"
BITNET_BIN="/mnt/models/bitnet-bin/llama-server"
LLAMA_BIN="/mnt/models/llamacpp-bin/llama-server"
BITNET_MODEL="/mnt/models/models/bitnet-b1.58-2B-4T-i2_s.gguf"
Q4_MODEL="/mnt/models/models/llama-3.1-8b-instruct-Q4_K_M.gguf"
Q8_MODEL="/mnt/models/models/llama-3.1-8b-instruct-Q8_0.gguf"
Q70_MODEL="/mnt/models/models/llama-3.3-70b-instruct-Q4_K_M.gguf"
LOGS="$HOME/logs/legA-snp-twin"
mkdir -p "$LOGS" runs

stop_runtimes() {
  pkill -f 'llama-server.*--port 860[1-4]' 2>/dev/null || true
  sleep 3
}

start_runtimes() {
  local threads="$1"
  stop_runtimes
  env LD_LIBRARY_PATH=/mnt/models/bitnet-bin nohup "$BITNET_BIN" \
    -m "$BITNET_MODEL" --port 8601 --host 127.0.0.1 -t "$threads" \
    -c 16384 --parallel 8 --cont-batching --no-warmup \
    >"$LOGS/bitnet-t${threads}.log" 2>&1 &
  env LD_LIBRARY_PATH=/mnt/models/llamacpp-bin nohup "$LLAMA_BIN" \
    -m "$Q4_MODEL" --port 8602 --host 127.0.0.1 -t "$threads" \
    -c 16384 --parallel 8 --cont-batching --no-warmup \
    >"$LOGS/8b-q4-t${threads}.log" 2>&1 &
  env LD_LIBRARY_PATH=/mnt/models/llamacpp-bin nohup "$LLAMA_BIN" \
    -m "$Q8_MODEL" --port 8603 --host 127.0.0.1 -t "$threads" \
    -c 16384 --parallel 8 --cont-batching --no-warmup \
    >"$LOGS/8b-q8-t${threads}.log" 2>&1 &
  env LD_LIBRARY_PATH=/mnt/models/llamacpp-bin nohup "$LLAMA_BIN" \
    -m "$Q70_MODEL" --port 8604 --host 127.0.0.1 -t "$threads" \
    -c 16384 --parallel 8 --cont-batching --no-warmup \
    >"$LOGS/70b-q4-t${threads}.log" 2>&1 &
  for port in 8601 8602 8603 8604; do
    for _ in $(seq 1 360); do
      curl -sf --max-time 2 "http://127.0.0.1:${port}/health" >/dev/null && break
      sleep 2
    done
    curl -sf --max-time 2 "http://127.0.0.1:${port}/health" >/dev/null || exit 3
  done
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
