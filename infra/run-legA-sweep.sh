#!/usr/bin/env bash
# Leg-A thread-saturation sweep (run ON the box). Restarts llama-servers at each
# thread count so the recorded `threads` matches the actual engine threads, then
# runs the matrix cells for that T. Resumable (run_ids dedupe in the JSONL).
# Runs long (70B is single-digit tok/s) — launch under nohup.
set -uo pipefail
cd "$HOME/verified-inference" || exit 1
export PATH="$HOME/.local/bin:$PATH"
OUT="runs/legA-full.jsonl"
LLAMA="$HOME/src/llama.cpp/build/bin/llama-server"
BITNET="$HOME/src/BitNet/build/bin/llama-server"
BN_MODEL="$HOME/src/BitNet/models/BitNet-b1.58-2B-4T/ggml-model-i2_s.gguf"
M="$HOME/models"
mkdir -p runs "$HOME/logs"

stop_all() { pkill -f "port 860" 2>/dev/null; sleep 3; }
# ensure the vinfer proxy server (real backend) is up; it forwards to whatever
# llama-server is currently listening on 8601-8604.
if ! curl -s http://127.0.0.1:8477/healthz | grep -q '"ok"'; then
  VINFER_BACKEND=llama VINFER_SEV_MODE=off nohup uv run uvicorn server.main:app --port 8477 \
    >"$HOME/logs/vinfer-sweep.log" 2>&1 &
  sleep 5
fi
wait_health() { for p in 8601 8602 8603 8604; do
  for _ in $(seq 1 180); do
    if curl -s "http://127.0.0.1:$p/health" | grep -q '"ok"'; then break; fi
    sleep 5
  done; done; }

for T in 16 32 64 128; do
  echo "═══ threads=$T $(date -u +%H:%M:%S) ═══"
  stop_all
  nohup "$BITNET" -m "$BN_MODEL" --port 8601 --host 127.0.0.1 -t "$T" -c 4096 >"$HOME/logs/sw-bitnet-$T.log" 2>&1 &
  nohup "$LLAMA" -m "$M/llama-3.1-8b-instruct-Q4_K_M.gguf" --port 8602 --host 127.0.0.1 -t "$T" -c 16384 --no-warmup >"$HOME/logs/sw-8bq4-$T.log" 2>&1 &
  nohup "$LLAMA" -m "$M/llama-3.1-8b-instruct-Q8_0.gguf"  --port 8603 --host 127.0.0.1 -t "$T" -c 16384 --no-warmup >"$HOME/logs/sw-8bq8-$T.log" 2>&1 &
  nohup "$LLAMA" -m "$M/llama-3.3-70b-instruct-Q4_K_M.gguf" --port 8604 --host 127.0.0.1 -t "$T" -c 16384 --no-warmup >"$HOME/logs/sw-70b-$T.log" 2>&1 &
  wait_health
  # per-T matrix (threads pinned to this T)
  python3 - "$T" > "/tmp/matrix-$T.json" <<'PY'
import json, sys
T = int(sys.argv[1])
print(json.dumps({"n_per_cell": 10, "grid": {
  "leg": ["A"], "model": ["bitnet-2b","8b-q4","8b-q8","70b-q4"],
  "prompt_tokens": [128,1024], "output_tokens": [128],
  "threads": [T], "concurrency": [1], "input_mode": ["tls"],
  "numa_policy": ["nps1-default"]}}))
PY
  VINFER_BACKEND=llama VINFER_SEV_MODE=off VINFER_URL=http://127.0.0.1:8477 \
    uv run python -m harness.runner "/tmp/matrix-$T.json" "$OUT" || echo "runner error at T=$T"
  echo "── done T=$T; lines so far: $(wc -l < "$OUT")"
done
stop_all
echo "SWEEP COMPLETE $(date -u +%H:%M:%S); total $(wc -l < "$OUT") records"
