#!/usr/bin/env bash
# Fetch GLM-5.2 GGUF to the NVMe and fill its models.yaml hash (run ON the box).
# GLM-5.2 = open-weight 744B-total/40B-active MoE; Unsloth dynamic GGUF, sharded (~450GB
# at UD-Q4_K_XL). NVMe is 6.4TB so there's room. Waits for the leg-A sweep first.
set -uo pipefail
M="$HOME/models/GLM-5.2-UD-Q4_K_XL"
REPO="unsloth/GLM-5.2-GGUF"
PAT="UD-Q4_K_XL"          # matches the quant subfolder / filenames
export PATH="$HOME/.local/bin:$PATH"
export HF_HUB_ENABLE_HF_TRANSFER=1

# don't compete with the sweep for memory bandwidth / disk
while pgrep -f run-legA-sweep.sh >/dev/null; do echo "sweep running; wait 300s"; sleep 300; done

mkdir -p "$M"
echo "downloading $REPO  (pattern *$PAT*) ..."
uv run --with "huggingface_hub[cli,hf_transfer]" hf download "$REPO" \
  --include "*$PAT*" --local-dir "$M" || {
    echo "ERROR: hf download failed"; exit 1; }

# guard: refuse to fabricate a hash if nothing downloaded
shopt -s nullglob
shards=("$M"/**/*.gguf "$M"/*.gguf)
if [ ${#shards[@]} -eq 0 ]; then
  echo "ERROR: no .gguf shards under $M — nothing downloaded; not writing a hash"
  exit 1
fi
echo "got ${#shards[@]} shard(s):"; printf '  %s\n' "${shards[@]}"

# sharded-model registry hash = sha256 of sorted newline-joined per-shard sha256s
RH=$(for f in $(printf '%s\n' "${shards[@]}" | sort); do sha256sum "$f" | awk '{print $1}'; done \
     | sha256sum | awk '{print $1}')
FIRST=$(printf '%s\n' "${shards[@]}" | sort | grep -m1 -iE '00001|split-00001' || printf '%s\n' "${shards[@]}" | sort | head -1)
echo "$RH" > "$M/.registry_sha256"
echo "GLM-5.2 shard-set hash: $RH"
echo "first shard (llama-server -m): $FIRST"
echo "NEXT: set glm-5.2-q4 weights_sha256=$RH and weights=$FIRST in models.yaml"
