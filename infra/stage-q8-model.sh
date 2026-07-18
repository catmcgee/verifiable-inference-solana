#!/usr/bin/env bash
# Run on the Sunburst host while no VM has models.img open. Adds the already
# downloaded Q8 weights to the shared read-only guest model volume and verifies
# the registry hash. No model bytes or secrets enter this repository.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

if pgrep -f 'qemu-system-x86_64.*models.img' >/dev/null; then
  echo "FATAL: a VM still has models.img open" >&2
  exit 2
fi

REPO="$HOME/verified-inference"
IMAGE="$HOME/vms/models.img"
MOUNT=/mnt/vinfer-model-stage
readarray -t MODEL < <(cd "$REPO" && uv run python - <<'PY'
import yaml
for model in yaml.safe_load(open('models.yaml')):
    if model['id'] == '8b-q8':
        print(model['weights'])
        print(model['weights_sha256'])
        break
else:
    raise SystemExit('8b-q8 is absent from models.yaml')
PY
)
SOURCE="${MODEL[0]}"
EXPECTED="${MODEL[1]}"
DEST_NAME=$(basename "$SOURCE")

test -f "$SOURCE"
test "$(sha256sum "$SOURCE" | awk '{print $1}')" = "$EXPECTED"
sudo mkdir -p "$MOUNT"
sudo mount -o loop,rw "$IMAGE" "$MOUNT"
cleanup() { sudo umount "$MOUNT" 2>/dev/null || true; }
trap cleanup EXIT
sudo install -m 0644 "$SOURCE" "$MOUNT/models/$DEST_NAME"
test "$(sudo sha256sum "$MOUNT/models/$DEST_NAME" | awk '{print $1}')" = "$EXPECTED"
sync
cleanup
trap - EXIT
echo "staged 8b-q8: $DEST_NAME ($EXPECTED)"
