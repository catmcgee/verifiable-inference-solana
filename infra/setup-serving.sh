#!/usr/bin/env bash
# P2/P3 provisioning — run ON the box (idempotent, safe to re-run).
# Builds llama.cpp + BitNet (bitnet.cpp), downloads the model ladder to the
# NVMe, installs the P3 virtualization stack (qemu/OVMF) + SNP tooling.
set -euo pipefail

MODELS_DIR="$HOME/models"
SRC_DIR="$HOME/src"
mkdir -p "$MODELS_DIR" "$SRC_DIR" "$HOME/logs"

echo "── apt deps"
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  cmake build-essential python3-venv python3-pip pkg-config git curl \
  clang lld ninja-build \
  qemu-system-x86 ovmf cloud-image-utils qemu-utils \
  cargo rustc musl-tools >/dev/null

echo "── llama.cpp"
if [ ! -d "$SRC_DIR/llama.cpp" ]; then
  git clone --depth 1 https://github.com/ggml-org/llama.cpp "$SRC_DIR/llama.cpp"
fi
if [ ! -x "$SRC_DIR/llama.cpp/build/bin/llama-server" ]; then
  cmake -S "$SRC_DIR/llama.cpp" -B "$SRC_DIR/llama.cpp/build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DLLAMA_CURL=OFF >/dev/null
  cmake --build "$SRC_DIR/llama.cpp/build" --target llama-server llama-cli llama-bench -j"$(nproc)" >/dev/null
fi
"$SRC_DIR/llama.cpp/build/bin/llama-cli" --version 2>&1 | head -2 || true

echo "── BitNet (bitnet.cpp)"
if [ ! -d "$SRC_DIR/BitNet" ]; then
  git clone --recursive --depth 1 https://github.com/microsoft/BitNet "$SRC_DIR/BitNet"
fi
if [ ! -d "$SRC_DIR/BitNet/.venv" ]; then
  python3 -m venv "$SRC_DIR/BitNet/.venv"
  "$SRC_DIR/BitNet/.venv/bin/pip" -q install -r "$SRC_DIR/BitNet/requirements.txt"
fi

echo "── model downloads (background-friendly; resumable)"
dl() { # dl <url> <dest>
  local url="$1" dest="$2"
  if [ -f "$dest" ] && [ ! -f "$dest.part" ]; then echo "have $(basename "$dest")"; return; fi
  echo "fetching $(basename "$dest")"
  curl -fL --retry 5 -C - -o "$dest.part" "$url" && mv "$dest.part" "$dest"
}
HF=https://huggingface.co
dl "$HF/microsoft/BitNet-b1.58-2B-4T-gguf/resolve/main/ggml-model-i2_s.gguf" \
   "$MODELS_DIR/bitnet-b1.58-2B-4T-i2_s.gguf"
dl "$HF/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf" \
   "$MODELS_DIR/llama-3.1-8b-instruct-Q4_K_M.gguf"
dl "$HF/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q8_0.gguf" \
   "$MODELS_DIR/llama-3.1-8b-instruct-Q8_0.gguf"
dl "$HF/bartowski/Llama-3.3-70B-Instruct-GGUF/resolve/main/Llama-3.3-70B-Instruct-Q4_K_M.gguf" \
   "$MODELS_DIR/llama-3.3-70b-instruct-Q4_K_M.gguf"

echo "── BitNet model kernel prep (generates i2_s kernels + builds bitnet llama.cpp fork)"
if [ ! -x "$SRC_DIR/BitNet/build/bin/llama-server" ]; then
  cd "$SRC_DIR/BitNet"
  mkdir -p models/BitNet-b1.58-2B-4T
  cp -n "$MODELS_DIR/bitnet-b1.58-2B-4T-i2_s.gguf" models/BitNet-b1.58-2B-4T/ggml-model-i2_s.gguf || true
  ".venv/bin/python" setup_env.py -md models/BitNet-b1.58-2B-4T -q i2_s || echo "bitnet setup_env failed — check logs"
fi

echo "── SNP guest tooling (snpguest, sevctl via cargo)"
export PATH="$HOME/.cargo/bin:$PATH"
command -v snpguest >/dev/null || cargo install -q snpguest 2>/dev/null || echo "snpguest install deferred"
command -v sevctl   >/dev/null || cargo install -q sevctl   2>/dev/null || echo "sevctl install deferred"

echo "── weights hashes (for attestation binding)"
for f in "$MODELS_DIR"/*.gguf; do
  [ -f "$f" ] && sha256sum "$f"
done | tee "$MODELS_DIR/SHA256SUMS"

echo "done."
