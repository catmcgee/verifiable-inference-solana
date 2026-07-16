#!/usr/bin/env bash
# Fetch GLM-5.2 GGUF to the NVMe and fill its models.yaml hash (run ON the box).
# GLM-5.2 = Z.ai 744B-total/40B-active MoE; Unsloth dynamic GGUF, sharded.
# Waits for the leg-A sweep to finish first (avoid perturbing measurements).
# The UD-Q4_K_XL set is large (~450GB); NVMe is 6.4TB so there's room.
set -uo pipefail
M="$HOME/models/GLM-5.2-UD-Q4_K_XL"
REPO="unsloth/GLM-5.2-GGUF"
SUB="UD-Q4_K_XL"
export PATH="$HOME/.local/bin:$PATH"

# don't compete with the sweep for memory bandwidth / disk
while pgrep -f run-legA-sweep.sh >/dev/null; do echo "sweep running; wait 300s"; sleep 300; done

mkdir -p "$M"
pip install -q --user "huggingface_hub[cli]" 2>/dev/null || true
echo "downloading $REPO/$SUB ..."
hf download "$REPO" --include "*$SUB*" --local-dir "$M" || \
  huggingface-cli download "$REPO" --include "*$SUB*" --local-dir "$M"

# registry hash for a sharded model = sha256 of the sorted newline-joined
# per-shard sha256 list (documented in models.yaml header).
cd "$M"
LIST=$(for f in $(ls *.gguf | sort); do sha256sum "$f" | awk '{print $1}'; done)
RH=$(printf '%s\n' "$LIST" | sha256sum | awk '{print $1}')
echo "GLM-5.2 shard-set hash: $RH"
echo "$RH" > "$M/.registry_sha256"
echo "Now set weights_sha256 for glm-5.2-q4 in models.yaml to: $RH"
echo "(first shard for llama-server -m: $(ls *00001* 2>/dev/null | head -1))"
