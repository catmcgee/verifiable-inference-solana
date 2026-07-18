#!/usr/bin/env bash
# Run inside the 32-vCPU SNP guest. Produces the protocol-matched feasible
# matrix: 16/32 threads, prompt 128/1024, concurrency 1/4/8, TLS plus HPKE.
set -euo pipefail

cd "$HOME/verified-inference"
export PATH="$HOME/.local/bin:$PATH"

if [ ! -c /dev/sev-guest ]; then
  echo "FATAL: /dev/sev-guest is absent; refusing to label this leg SNP" >&2
  exit 2
fi
if [ ! -r /dev/sev-guest ] || [ ! -w /dev/sev-guest ]; then
  sudo chgrp "$(id -gn)" /dev/sev-guest
  sudo chmod 0660 /dev/sev-guest
fi
test -r /dev/sev-guest -a -w /dev/sev-guest

OUT="runs/legB-snp-full.jsonl"
BITNET_BIN="/mnt/models/bitnet-bin/llama-server"
LLAMA_BIN="/mnt/models/llamacpp-bin/llama-server"
BITNET_MODEL="/mnt/models/models/bitnet-b1.58-2B-4T-i2_s.gguf"
Q4_MODEL="/mnt/models/models/llama-3.1-8b-instruct-Q4_K_M.gguf"
Q70_MODEL="/mnt/models/models/llama-3.3-70b-instruct-Q4_K_M.gguf"
LOGS="$HOME/logs/legB-snp"
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
    -m "$Q70_MODEL" --port 8604 --host 127.0.0.1 -t "$threads" \
    -c 16384 --parallel 8 --cont-batching --no-warmup \
    >"$LOGS/70b-q4-t${threads}.log" 2>&1 &

  for port in 8601 8602 8604; do
    for _ in $(seq 1 360); do
      if curl -sf --max-time 2 "http://127.0.0.1:${port}/health" >/dev/null; then
        echo "runtime :${port} healthy"
        break
      fi
      sleep 2
    done
    curl -sf --max-time 2 "http://127.0.0.1:${port}/health" >/dev/null || {
      echo "FATAL: runtime :${port} failed to start" >&2
      exit 3
    }
  done
}

restart_vinfer() {
  pkill -f 'uvicorn server.main:app' 2>/dev/null || true
  sleep 2
  VINFER_SEV_MODE=snp \
  VINFER_AVAILABLE_MODELS=bitnet-2b,8b-q4,70b-q4 \
    nohup uv run uvicorn server.main:app --host 0.0.0.0 --port 8477 \
    >"$LOGS/vinfer.log" 2>&1 &
  for _ in $(seq 1 60); do
    curl -sf --max-time 2 http://127.0.0.1:8477/healthz >/dev/null && break
    sleep 1
  done
  curl -sf http://127.0.0.1:8477/v1/attestation >/tmp/legB-attestation.json
  python3 - <<'PY'
import base64, json, struct
d = json.load(open('/tmp/legB-attestation.json'))
r = base64.b64decode(d['snp_report_b64'])
assert d['grade'] == 'snp'
assert struct.unpack_from('<I', r, 0x30)[0] == 0
assert sorted(x['id'] for x in d['registry']) == ['70b-q4', '8b-q4', 'bitnet-2b']
print('attestation: grade=snp VMPL=0 registry=3')
PY
}

run_matrix() {
  local matrix="$1"
  VINFER_URL=http://127.0.0.1:8477 uv run python -m harness.runner "$matrix" "$OUT"
}

for threads in 16 32; do
  echo "=== SNP threads=${threads} ==="
  start_runtimes "$threads"
  if [ "$threads" = 16 ]; then
    restart_vinfer
  fi
  matrix="/tmp/legB-snp-t${threads}.json"
  python3 - "$threads" "$matrix" <<'PY'
import json, sys
t, path = int(sys.argv[1]), sys.argv[2]
json.dump({"n_per_cell": 10, "grid": {
  "leg": ["B"], "model": ["bitnet-2b", "8b-q4", "70b-q4"],
  "prompt_tokens": [128, 1024], "output_tokens": [128],
  "threads": [t], "concurrency": [1], "input_mode": ["tls"],
  "numa_policy": ["guest-single-numa"]}}, open(path, "w"))
PY
  run_matrix "$matrix"
done

# Concurrency and HPKE at the best feasible thread count (32 physical vCPUs).
python3 - <<'PY'
import json
base = {"leg": ["B"], "model": ["bitnet-2b", "8b-q4", "70b-q4"],
        "prompt_tokens": [128, 1024], "output_tokens": [128], "threads": [32],
        "numa_policy": ["guest-single-numa"]}
json.dump({"n_per_cell": 10, "grid": {**base, "concurrency": [4, 8],
          "input_mode": ["tls"]}}, open('/tmp/legB-snp-concurrency.json', 'w'))
json.dump({"n_per_cell": 10, "grid": {**base, "prompt_tokens": [128],
          "concurrency": [1], "input_mode": ["hpke"]}},
          open('/tmp/legB-snp-hpke.json', 'w'))
PY
run_matrix /tmp/legB-snp-concurrency.json
run_matrix /tmp/legB-snp-hpke.json

echo "Leg B SNP sweep complete: $(wc -l < "$OUT") rows -> $OUT"
