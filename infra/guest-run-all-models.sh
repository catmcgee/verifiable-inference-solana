#!/usr/bin/env bash
# Start all five registry runtimes and the authenticated vinfer origin.
# Run inside the 832 GiB GLM SNP guest after repo/uv/token provisioning.
set -euo pipefail

ROOT=${VINFER_ROOT:-$HOME/verified-inference}
THREADS=${VINFER_THREADS:-64}
SMALL_MOUNT=${VINFER_SMALL_MOUNT:-/mnt/models}
GLM_MOUNT=${VINFER_GLM_MOUNT:-/mnt/glm}
TOKEN_FILE=${VINFER_ORIGIN_TOKEN_FILE:-$HOME/.config/vinfer/origin-token}
RELAY_TOKEN_FILE=${VINFER_RECEIPT_RELAY_TOKEN_FILE:-$HOME/.config/vinfer/receipt-relay-token}

if ! test -c /dev/sev-guest; then
  sudo modprobe sev_guest
fi
test -c /dev/sev-guest
mem_kib=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
test "$mem_kib" -ge 838000000 || {
  echo "guest has less than 800 GiB RAM" >&2
  exit 2
}
sudo mkdir -p "$SMALL_MOUNT" "$GLM_MOUNT"
mountpoint -q "$SMALL_MOUNT" || sudo mount -o ro /dev/vdc "$SMALL_MOUNT"
mountpoint -q "$GLM_MOUNT" || sudo mount -o ro /dev/vdd "$GLM_MOUNT"
test -s "$TOKEN_FILE"
test "$(stat -c %a "$TOKEN_FILE")" = 600
test -s "$RELAY_TOKEN_FILE"
test "$(stat -c %a "$RELAY_TOKEN_FILE")" = 600

cd "$ROOT"
export PATH="$HOME/.local/bin:$PATH"
expected=$(uv run python - <<'PY'
from server import registry
print(registry.load()["glm-5.2-q4"].weights_sha256)
PY
)
test "$(cat "$GLM_MOUNT/.registry_sha256")" = "$expected"
glm_first=$(find "$GLM_MOUNT" -type f -name '*00001-of-00011.gguf' -print -quit)
test -n "$glm_first"
for runtime_dir in \
  "$GLM_MOUNT/llamacpp-bin" \
  "$SMALL_MOUNT/llamacpp-bin" \
  "$SMALL_MOUNT/bitnet-bin"; do
  missing=$(LD_LIBRARY_PATH="$runtime_dir" ldd "$runtime_dir/llama-server" \
    | awk '/not found/ {print $1}')
  test -z "$missing" || {
    echo "missing runtime libraries for $runtime_dir: $missing" >&2
    exit 2
  }
done

pkill -f llama-server 2>/dev/null || true
pkill -f 'uvicorn server.main:app' 2>/dev/null || true
sleep 2
mkdir -p "$HOME/logs/vinfer" "$HOME/.local/state/vinfer"

LD_LIBRARY_PATH="$GLM_MOUNT/llamacpp-bin" \
  nohup "$GLM_MOUNT/llamacpp-bin/llama-server" \
    -m "$glm_first" --port 8605 --host 127.0.0.1 -t "$THREADS" -c 8192 \
    --jinja --no-warmup > "$HOME/logs/vinfer/glm.log" 2>&1 &

for _ in $(seq 1 3600); do
  curl -sf --max-time 2 http://127.0.0.1:8605/health >/dev/null && break
  sleep 1
done
curl -sf http://127.0.0.1:8605/health >/dev/null

LD_LIBRARY_PATH="$SMALL_MOUNT/bitnet-bin" \
  nohup "$SMALL_MOUNT/bitnet-bin/llama-server" \
    -m "$SMALL_MOUNT/models/bitnet-b1.58-2B-4T-i2_s.gguf" \
    --port 8601 --host 127.0.0.1 -t "$THREADS" -c 4096 --no-warmup \
    > "$HOME/logs/vinfer/bitnet.log" 2>&1 &
for spec in \
  '8602 llama-3.1-8b-instruct-Q4_K_M.gguf' \
  '8603 llama-3.1-8b-instruct-Q8_0.gguf' \
  '8604 llama-3.3-70b-instruct-Q4_K_M.gguf'; do
  read -r port weight <<< "$spec"
  LD_LIBRARY_PATH="$SMALL_MOUNT/llamacpp-bin" \
    nohup "$SMALL_MOUNT/llamacpp-bin/llama-server" \
      -m "$SMALL_MOUNT/models/$weight" --port "$port" --host 127.0.0.1 \
      -t "$THREADS" -c 8192 --no-warmup \
      > "$HOME/logs/vinfer/model-$port.log" 2>&1 &
done
for port in 8601 8602 8603 8604; do
  for _ in $(seq 1 900); do
    curl -sf --max-time 2 "http://127.0.0.1:$port/health" >/dev/null && break
    sleep 1
  done
  curl -sf "http://127.0.0.1:$port/health" >/dev/null
done

if ! test -r /dev/sev-guest -a -w /dev/sev-guest; then
  sudo chgrp "$(id -gn)" /dev/sev-guest
  sudo chmod 0660 /dev/sev-guest
fi
VINFER_SEV_MODE=snp \
VINFER_REQUIRE_AUTH=1 \
VINFER_AUTH_TOKEN="$(cat "$TOKEN_FILE")" \
VINFER_AUTH_COOKIE_PATH=/ \
VINFER_AUTH_SECURE_COOKIE=1 \
VINFER_RECEIPT_RELAY_URL=http://10.0.2.2:8480 \
VINFER_RECEIPT_RELAY_TOKEN_FILE="$RELAY_TOKEN_FILE" \
VINFER_AVAILABLE_MODELS='bitnet-2b,8b-q4,8b-q8,70b-q4,glm-5.2-q4' \
  nohup uv run uvicorn server.main:app --host 0.0.0.0 --port 8477 \
  > "$HOME/logs/vinfer/origin.log" 2>&1 &

for _ in $(seq 1 120); do
  curl -sf --max-time 2 http://127.0.0.1:8477/healthz >/dev/null && break
  sleep 1
done
curl -sf http://127.0.0.1:8477/healthz
