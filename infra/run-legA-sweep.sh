#!/usr/bin/env bash
# Leg-A thread-saturation sweep (run ON the box). Restarts llama-servers at each
# thread count so the recorded `threads` matches the actual engine threads, then
# runs the matrix cells for that T. Resumable (run_ids dedupe in the JSONL).
# Runs long (70B is single-digit tok/s) — launch under nohup.
set -uo pipefail
cd "$HOME/verified-inference" || exit 1
export PATH="$HOME/.local/bin:$PATH"
OUT="runs/legA-full.jsonl"
mkdir -p runs "$HOME/logs"
RUNTIME_PID=

stop_all() {
  if [ -n "$RUNTIME_PID" ]; then
    kill "$RUNTIME_PID" 2>/dev/null || true
    wait "$RUNTIME_PID" 2>/dev/null || true
    RUNTIME_PID=
  fi
}
trap stop_all EXIT
# Ensure the vinfer API is up; model endpoints come from models.yaml.
if ! curl -s http://127.0.0.1:8477/healthz | grep -q '"ok"'; then
  VINFER_BACKEND=llama VINFER_SEV_MODE=off nohup uv run uvicorn server.main:app --port 8477 \
    >"$HOME/logs/vinfer-sweep.log" 2>&1 &
  sleep 5
fi
for T in 16 32 64 128; do
  echo "═══ threads=$T $(date -u +%H:%M:%S) ═══"
  stop_all
  nohup uv run python -m server.serve_models \
    --models bitnet-2b,8b-q4,8b-q8,70b-q4 --threads "$T" --context-cap 16384 \
    >"$HOME/logs/models-t$T.log" 2>&1 &
  RUNTIME_PID=$!
  uv run python -m server.serve_models \
    --models bitnet-2b,8b-q4,8b-q8,70b-q4 --status --startup-timeout 900
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
echo "SWEEP COMPLETE $(date -u +%H:%M:%S); total $(wc -l < "$OUT") records"
