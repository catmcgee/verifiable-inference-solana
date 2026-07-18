#!/usr/bin/env bash
# Build the read-only GLM block image used by the large SNP guest.
# Run on the Sunburst host. models.yaml remains the source of path/hash truth.
set -euo pipefail

ROOT=${VINFER_ROOT:-$HOME/verified-inference}
IMAGE=${VINFER_GLM_IMAGE:-$HOME/vms/glm-models.img}
IMAGE_SIZE=${VINFER_GLM_IMAGE_SIZE:-500G}
MOUNT=${VINFER_GLM_STAGE_MOUNT:-/mnt/vinfer-glm-stage}

cd "$ROOT"
export PATH="$HOME/.local/bin:$PATH"
readarray -t registry < <(uv run python - <<'PY'
from server import registry
model = registry.load()["glm-5.2-q4"]
print(model.weights)
print(model.weights_sha256)
PY
)
FIRST=${registry[0]}
EXPECTED=${registry[1]}
SOURCE=$(dirname "$FIRST")
RELATIVE=${SOURCE#"$HOME/models/"}

test -f "$FIRST"
test "$SOURCE" != "$RELATIVE" || {
  echo "GLM weights must live below $HOME/models" >&2
  exit 2
}
if pgrep -af qemu-system | grep -F -- "$IMAGE" >/dev/null; then
  echo "$IMAGE is attached to a running VM" >&2
  exit 2
fi

if test ! -e "$IMAGE"; then
  truncate -s "$IMAGE_SIZE" "$IMAGE"
  mkfs.ext4 -F -m 0 -L vinfer-glm "$IMAGE"
fi
test "$(blkid -o value -s TYPE "$IMAGE")" = ext4

sudo mkdir -p "$MOUNT"
sudo mount -o loop "$IMAGE" "$MOUNT"
cleanup() {
  mountpoint -q "$MOUNT" && sudo umount "$MOUNT"
}
trap cleanup EXIT

sudo mkdir -p "$MOUNT/$RELATIVE" "$MOUNT/llamacpp-bin"
sudo chown -R "$(id -u):$(id -g)" "$MOUNT/$RELATIVE" "$MOUNT/llamacpp-bin"
rsync -a --info=progress2 "$SOURCE/" "$MOUNT/$RELATIVE/"
rsync -a "$HOME/src/llama.cpp/build/bin/" "$MOUNT/llamacpp-bin/"

mapfile -d '' shards < <(find "$MOUNT/$RELATIVE" -maxdepth 1 -type f -name '*.gguf' -print0 | sort -z)
test "${#shards[@]}" -eq 11 || {
  echo "expected 11 GGUF shards, found ${#shards[@]}" >&2
  exit 2
}
ACTUAL=$(for shard in "${shards[@]}"; do sha256sum "$shard" | awk '{print $1}'; done \
  | sha256sum | awk '{print $1}')
test "$ACTUAL" = "$EXPECTED" || {
  echo "copied shard-set hash does not match models.yaml" >&2
  exit 2
}
printf '%s\n' "$ACTUAL" | sudo tee "$MOUNT/.registry_sha256" >/dev/null
sync
echo "GLM model image ready: $IMAGE; 11 shards; registry hash verified"
