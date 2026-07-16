#!/usr/bin/env bash
# in-guest-measure.sh -- runs inside a measurement guest.
# Env: SEV_MODE (off|es|snp), LEG (A|B), THREADS (default 32).
# Runs STREAM triad (identical binary across legs) + optional inference.
# Writes ~/stream.txt and ~/ab.jsonl in the guest.
set -uo pipefail

SEV_MODE="${SEV_MODE:-off}"
LEG="${LEG:-A}"
THREADS="${THREADS:-32}"

echo "[measure] LEG=$LEG SEV_MODE=$SEV_MODE THREADS=$THREADS host=$(hostname) kernel=$(uname -r)"

BIN="$HOME/stream.bin"
SRC="$HOME/stream.c"

# Prefer the prebuilt static binary shipped from the box (identical across legs).
if [ ! -x "$BIN" ]; then
  if [ -f "$SRC" ]; then
    echo "[measure] no prebuilt binary; compiling $SRC in guest"
    if ! command -v gcc >/dev/null 2>&1; then
      echo "[measure] installing gcc..."
      sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq || true
      sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq gcc >/dev/null 2>&1 || true
    fi
    gcc -O3 -fopenmp -DSTREAM_ARRAY_SIZE=80000000 -DNTIMES=20 -o "$BIN" "$SRC" \
      || { echo "[measure] FATAL: compile failed"; exit 2; }
  else
    echo "[measure] FATAL: no $BIN and no $SRC"; exit 2
  fi
fi

echo "[measure] running STREAM triad with OMP_NUM_THREADS=$THREADS ..."
OMP_NUM_THREADS="$THREADS" OMP_PROC_BIND=spread OMP_PLACES=cores "$BIN" | tee "$HOME/stream.txt"

TRIAD=$(grep '^TRIAD_GBS' "$HOME/stream.txt" | awk '{print $2}')
echo "[measure] Triad = ${TRIAD:-NA} GB/s"

# --- optional inference (no-op unless a local llama-server is staged) ---
INFER_TPS=0
if curl -s --max-time 2 http://127.0.0.1:8080/health 2>/dev/null | grep -q '"ok"'; then
  echo "[measure] local inference server detected; (inference measurement not staged here)"
else
  echo "[measure] no inference server staged -- skipping inference (STREAM is the priority)"
fi

# --- ab.jsonl marker ---
KERNEL=$(uname -r)
printf '{"leg":"%s","sev_mode":"%s","threads":%s,"stream_triad_gbs":%s,"kernel":"%s","infer_tps":%s}\n' \
  "$LEG" "$SEV_MODE" "$THREADS" "${TRIAD:-0}" "$KERNEL" "$INFER_TPS" > "$HOME/ab.jsonl"

echo "[measure] done. wrote ~/stream.txt and ~/ab.jsonl"
