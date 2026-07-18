#!/usr/bin/env bash
# Build immutable root/model verification artifacts from the running large SNP guest.
# Run on the Sunburst host. It never stops or mutates a running VM disk/model image.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

ROOT=${VINFER_ROOT:-$HOME/verified-inference}
VMS=${VINFER_VM_DIR:-$HOME/vms}
SOURCE_PORT=${VINFER_SOURCE_SSH_PORT:-2223}
BOX_KEY=${VINFER_BOX_KEY:-$HOME/.ssh/id_ed25519_box}
OUT=${VINFER_MEASURED_PREFIX:-$VMS/vinfer-measured}
ROOT_SIZE=${VINFER_MEASURED_ROOT_SIZE:-12G}
MOUNT=${VINFER_MEASURED_MOUNT:-/mnt/vinfer-measured-root}
SMALL_IMAGE=${VINFER_SMALL_MODEL_IMAGE:-$VMS/models.img}
GLM_IMAGE=${VINFER_GLM_MODEL_IMAGE:-$VMS/glm-models.img}

ROOT_IMAGE=$OUT-root.img
ROOT_HASH_IMAGE=$OUT-root.verity
SMALL_HASH_IMAGE=$OUT-models.verity
GLM_HASH_IMAGE=$OUT-glm.verity
KERNEL=$OUT-vmlinuz
INITRD=$OUT-initrd.img
STATE=$OUT.env

for command in rsync ssh scp veritysetup mkfs.ext4 sha256sum python3 uv; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 2; }
done
for file in "$ROOT/models.yaml" "$BOX_KEY" "$SMALL_IMAGE" "$GLM_IMAGE"; do
  test -e "$file" || { echo "missing $file" >&2; exit 2; }
done
for artifact in \
  "$ROOT_IMAGE" "$ROOT_HASH_IMAGE" "$SMALL_HASH_IMAGE" \
  "$GLM_HASH_IMAGE" "$KERNEL" "$INITRD" "$STATE"; do
  test ! -e "$artifact" || { echo "refusing to overwrite $artifact" >&2; exit 2; }
done

guest_ssh=(ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -i "$BOX_KEY" -p "$SOURCE_PORT" ubuntu@127.0.0.1)
guest_scp=(scp -q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -i "$BOX_KEY" -P "$SOURCE_PORT")

# Build an initramfs that refuses to expose root until dm-verity succeeds.
"${guest_scp[@]}" \
  "$ROOT/infra/measured-boot/initramfs-hook" \
  "$ROOT/infra/measured-boot/initramfs-local-top" \
  ubuntu@127.0.0.1:/tmp/
"${guest_ssh[@]}" \
  'sudo install -m 0755 /tmp/initramfs-hook /etc/initramfs-tools/hooks/vinfer-verity; sudo install -m 0755 /tmp/initramfs-local-top /etc/initramfs-tools/scripts/local-top/vinfer-verity; sudo update-initramfs -u -k "$(uname -r)"; sudo install -m 0644 "/boot/vmlinuz-$(uname -r)" /tmp/vinfer-vmlinuz; sudo install -m 0644 "/boot/initrd.img-$(uname -r)" /tmp/vinfer-initrd.img'
"${guest_scp[@]}" ubuntu@127.0.0.1:/tmp/vinfer-vmlinuz "$KERNEL"
"${guest_scp[@]}" ubuntu@127.0.0.1:/tmp/vinfer-initrd.img "$INITRD"

truncate -s "$ROOT_SIZE" "$ROOT_IMAGE"
mkfs.ext4 -q -F -m 0 -L vinfer-measured-root "$ROOT_IMAGE"
sudo install -d -m 0755 "$MOUNT"
sudo mount -o loop "$ROOT_IMAGE" "$MOUNT"
cleanup() {
  mountpoint -q "$MOUNT" && sudo umount "$MOUNT"
}
trap cleanup EXIT

sudo rsync -aHAXx --numeric-ids \
  --rsync-path='sudo rsync' \
  -e "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i $BOX_KEY -p $SOURCE_PORT" \
  --exclude=/boot --exclude=/dev --exclude=/proc --exclude=/run --exclude=/sys \
  --exclude=/tmp --exclude=/mnt --exclude=/var/log --exclude=/var/tmp \
  --exclude=/home/ubuntu/.ssh --exclude=/root/.ssh \
  --exclude=/home/ubuntu/verified-inference/.git \
  ubuntu@127.0.0.1:/ "$MOUNT/"

# rsync excludes the live virtual filesystems, but initramfs still needs their
# empty mount points to exist before it can hand off to the real root.
sudo install -d -m 0755 \
  "$MOUNT/dev" "$MOUNT/proc" "$MOUNT/run" "$MOUNT/sys" \
  "$MOUNT/mnt" "$MOUNT/mnt/models" "$MOUNT/mnt/glm"
sudo install -d -m 1777 "$MOUNT/tmp" "$MOUNT/var/tmp"
sudo install -d -m 0755 "$MOUNT/var/log"

# Overlay the audited working tree, while preserving the guest venv and secrets.
sudo rsync -a \
  --exclude=.git --exclude=.venv --exclude=.env.local --exclude='*.pyc' \
  "$ROOT/" "$MOUNT/home/ubuntu/verified-inference/"
sudo chown -R ubuntu:ubuntu "$MOUNT/home/ubuntu/verified-inference"

sudo install -D -m 0755 "$ROOT/infra/measured-boot/vinfer-cmdline" \
  "$MOUNT/usr/local/lib/vinfer-cmdline"
for script in vinfer-write-boot-evidence vinfer-mount-models vinfer-start-models vinfer-start-origin; do
  sudo install -D -m 0755 "$ROOT/infra/measured-boot/$script" \
    "$MOUNT/usr/local/sbin/$script"
done
for unit in \
  vinfer-boot-evidence.service vinfer-model-images.service \
  vinfer-measured-models.service vinfer-measured-origin.service \
  vinfer-measured-proxy.service; do
  sudo install -D -m 0644 "$ROOT/infra/measured-boot/$unit" \
    "$MOUNT/etc/systemd/system/$unit"
done

# Registry paths remain authoritative; these links map them to verified images.
sudo install -d -o ubuntu -g ubuntu \
  "$MOUNT/home/ubuntu/models" \
  "$MOUNT/home/ubuntu/src/BitNet/models/BitNet-b1.58-2B-4T"
for name in \
  llama-3.1-8b-instruct-Q4_K_M.gguf \
  llama-3.1-8b-instruct-Q8_0.gguf \
  llama-3.3-70b-instruct-Q4_K_M.gguf; do
  sudo ln -s "/mnt/models/models/$name" "$MOUNT/home/ubuntu/models/$name"
done
sudo ln -s /mnt/glm/GLM-5.2-UD-Q4_K_XL "$MOUNT/home/ubuntu/models/GLM-5.2-UD-Q4_K_XL"
sudo ln -s /mnt/models/models/bitnet-b1.58-2B-4T-i2_s.gguf \
  "$MOUNT/home/ubuntu/src/BitNet/models/BitNet-b1.58-2B-4T/ggml-model-i2_s.gguf"

sudo tee "$MOUNT/etc/fstab" >/dev/null <<'EOF'
/dev/mapper/vinfer-root / ext4 ro,errors=remount-ro 0 1
tmpfs /tmp tmpfs rw,nosuid,nodev,noexec,mode=1777 0 0
tmpfs /var/log tmpfs rw,nosuid,nodev,noexec,mode=0755 0 0
tmpfs /var/tmp tmpfs rw,nosuid,nodev,noexec,mode=1777 0 0
EOF
sudo systemctl --root="$MOUNT" disable \
  ssh.service cloud-init.service cloud-config.service cloud-final.service \
  apt-daily.service apt-daily-upgrade.service 2>/dev/null || true
sudo systemctl --root="$MOUNT" mask \
  ssh.service ssh.socket cloud-init.service cloud-config.service cloud-final.service \
  apt-daily.service apt-daily-upgrade.service apt-daily.timer \
  apt-daily-upgrade.timer snapd.service snapd.socket snapd.seeded.service \
  snapd.failure.service >/dev/null
sudo systemctl --root="$MOUNT" enable \
  vinfer-boot-evidence.service vinfer-model-images.service \
  vinfer-measured-models.service vinfer-measured-origin.service \
  vinfer-measured-proxy.service >/dev/null
sudo systemctl --root="$MOUNT" disable vinfer-leg-c-proxy.service 2>/dev/null || true
sudo install -D -m 0644 /dev/null "$MOUNT/etc/machine-id"
sudo install -D -m 0644 /dev/null "$MOUNT/var/lib/dbus/machine-id"
sudo sync
sudo umount "$MOUNT"
trap - EXIT

hash_image_size() {
  python3 - "$1" <<'PY'
import os, sys
blocks = (os.path.getsize(sys.argv[1]) + 4095) // 4096
total = 1
while blocks > 1:
    blocks = (blocks + 127) // 128
    total += blocks
print((total + 4096) * 4096)
PY
}
format_verity() {
  data=$1
  hashes=$2
  truncate -s "$(hash_image_size "$data")" "$hashes"
  sudo veritysetup format --hash=sha256 "$data" "$hashes" \
    | awk -F: '/^Root hash:/ {gsub(/[[:space:]]/, "", $2); print $2}'
}

ROOT_HASH=$(format_verity "$ROOT_IMAGE" "$ROOT_HASH_IMAGE")
SMALL_HASH=$(format_verity "$SMALL_IMAGE" "$SMALL_HASH_IMAGE")
GLM_HASH=$(format_verity "$GLM_IMAGE" "$GLM_HASH_IMAGE")
for value in "$ROOT_HASH" "$SMALL_HASH" "$GLM_HASH"; do
  test "${#value}" -eq 64 || { echo "veritysetup did not return a root hash" >&2; exit 2; }
done

# Prove each registry path resolves through the verified root into the exact
# bytes declared for that model. Merely finding the same hash elsewhere in an
# image is not sufficient.
root_mount=/mnt/vinfer-root-verify
small_mount=/mnt/vinfer-models-verify
glm_mount=/mnt/vinfer-glm-verify
sudo install -d -m 0755 "$root_mount" "$small_mount" "$glm_mount"
sudo mount -o loop,ro "$ROOT_IMAGE" "$root_mount"
sudo mount -o loop,ro "$SMALL_IMAGE" "$small_mount"
sudo mount -o loop,ro "$GLM_IMAGE" "$glm_mount"
verify_cleanup() {
  mountpoint -q "$root_mount" && sudo umount "$root_mount"
  mountpoint -q "$small_mount" && sudo umount "$small_mount"
  mountpoint -q "$glm_mount" && sudo umount "$glm_mount"
}
trap verify_cleanup EXIT
cd "$ROOT"
ROOT="$ROOT" ROOT_MOUNT="$root_mount" SMALL_MOUNT="$small_mount" GLM_MOUNT="$glm_mount" uv run python - <<'PY'
import hashlib
import os
import re
from pathlib import Path
import yaml

entries = yaml.safe_load((Path(os.environ["ROOT"]) / "models.yaml").read_text())
root = Path(os.environ["ROOT_MOUNT"])
small = Path(os.environ["SMALL_MOUNT"])
glm = Path(os.environ["GLM_MOUNT"])

def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def resolved_weight(declared: str) -> Path:
    path = Path(declared)
    if not path.is_absolute():
        raise SystemExit(f"registry weight path must be absolute: {declared}")
    current = root
    parts = path.parts[1:]
    for index, part in enumerate(parts):
        current /= part
        if not current.is_symlink():
            continue
        target = Path(os.readlink(current))
        remaining = Path(*parts[index + 1:])
        if target == Path("/mnt/models") or Path("/mnt/models") in target.parents:
            return small / target.relative_to("/mnt/models") / remaining
        if target == Path("/mnt/glm") or Path("/mnt/glm") in target.parents:
            return glm / target.relative_to("/mnt/glm") / remaining
        raise SystemExit(f"registry path leaves verified model images: {declared}")
    raise SystemExit(f"registry path is not mapped to a verified model image: {declared}")

def declared_hash(path: Path) -> str:
    match = re.match(r"^(.*)-\d{5}-of-(\d{5})\.gguf$", path.name)
    if not match:
        if not path.is_file():
            raise SystemExit(f"verified weight file is absent: {path}")
        return sha(path)
    shards = sorted(path.parent.glob(f"{match.group(1)}-*-of-{match.group(2)}.gguf"))
    expected_count = int(match.group(2))
    if len(shards) != expected_count:
        raise SystemExit(
            f"verified shard set for {path.name} has {len(shards)} of {expected_count} files"
        )
    joined = "".join(f"{sha(shard)}\n" for shard in shards).encode()
    return hashlib.sha256(joined).hexdigest()

for entry in entries:
    actual = declared_hash(resolved_weight(entry["weights"]))
    if actual != entry["weights_sha256"]:
        raise SystemExit(f"resolved verified bytes do not match models.yaml for {entry['id']}")
PY
sudo umount "$root_mount"
sudo umount "$small_mount"
sudo umount "$glm_mount"
trap - EXIT

KERNEL_HASH=$(sha256sum "$KERNEL" | awk '{print $1}')
INITRD_HASH=$(sha256sum "$INITRD" | awk '{print $1}')
umask 022
cat > "$STATE" <<EOF
ROOT_HASH=$ROOT_HASH
SMALL_HASH=$SMALL_HASH
GLM_HASH=$GLM_HASH
KERNEL_HASH=$KERNEL_HASH
INITRD_HASH=$INITRD_HASH
EOF
chmod 0444 "$STATE"
echo "measured artifacts ready: $OUT (root/model bytes verified against models.yaml)"
