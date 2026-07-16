#!/usr/bin/env bash
# Start llama-server instances for the model ladder (run ON the box).
# Usage: ./run-servers.sh [threads]   (default 64 = physical cores)
# Ports must match models.yaml (the registry is the single source of truth).
set -euo pipefail
THREADS="${1:-64}"
MODELS="$HOME/models"
LLAMA="$HOME/src/llama.cpp/build/bin/llama-server"
BITNET="$HOME/src/BitNet/build/bin/llama-server"
LOGS="$HOME/logs"
mkdir -p "$LOGS"

start() { # start <name> <binary> <gguf> <port> [extra args...]
  local name="$1" bin="$2" gguf="$3" port="$4"; shift 4
  if curl -s "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
    echo "$name already up on :$port"; return
  fi
  echo "starting $name on :$port (threads=$THREADS)"
  nohup "$bin" -m "$gguf" --port "$port" --host 127.0.0.1 \
    -t "$THREADS" -c 16384 --no-warmup "$@" \
    >"$LOGS/$name.log" 2>&1 &
}

start bitnet-2b "$BITNET" "$HOME/src/BitNet/models/BitNet-b1.58-2B-4T/ggml-model-i2_s.gguf" 8601
start 8b-q4  "$LLAMA" "$MODELS/llama-3.1-8b-instruct-Q4_K_M.gguf" 8602
start 8b-q8  "$LLAMA" "$MODELS/llama-3.1-8b-instruct-Q8_0.gguf" 8603
start 70b-q4 "$LLAMA" "$MODELS/llama-3.3-70b-instruct-Q4_K_M.gguf" 8604
# GLM-5.2 needs --jinja for its chat template; raw /completion works without it
start glm-5.2-q4 "$LLAMA" "$MODELS/GLM-5.2-UD-Q4_K_XL/UD-Q4_K_XL/GLM-5.2-UD-Q4_K_XL-00001-of-00011.gguf" 8605 --jinja

echo "waiting for health..."
for p in 8601 8602 8603 8604 8605; do
  for i in $(seq 1 120); do
    curl -s "http://127.0.0.1:$p/health" | grep -q '"ok"\|"status"' && { echo ":$p healthy"; break; } || sleep 5
  done
done
