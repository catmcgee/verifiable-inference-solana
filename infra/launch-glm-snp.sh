#!/usr/bin/env bash
# Launch the large all-model SNP guest alongside the current public guest.
# Run on the Sunburst host. It does not stop or replace any existing VM.
set -euo pipefail

QEMU=${VINFER_QEMU:-$HOME/src/AMDSEV/usr/local/bin/qemu-system-x86_64}
BIOS=${VINFER_OVMF:-$HOME/vms/OVMF-snp.fd}
BASE=${VINFER_BASE_IMAGE:-$HOME/vms/noble-server-cloudimg-amd64.img}
VMS=${VINFER_VM_DIR:-$HOME/vms}
NAME=${VINFER_GLM_VM_NAME:-glm-snp}
CPUS=${VINFER_GLM_CPUS:-64}
RAM=${VINFER_GLM_RAM:-832G}
SSH_PORT=${VINFER_GLM_SSH_PORT:-2223}
API_PORT=${VINFER_GLM_API_PORT:-8479}
PROXY_PORT=${VINFER_GLM_PROXY_PORT:-8482}
DISK="$VMS/$NAME.qcow2"
SEED="$VMS/$NAME-seed.img"
SMALL_MODELS="$VMS/models.img"
GLM_MODELS="$VMS/glm-models.img"

for file in "$QEMU" "$BIOS" "$BASE" "$SMALL_MODELS" "$GLM_MODELS"; do
  test -e "$file" || { echo "missing $file" >&2; exit 2; }
done
if pgrep -af qemu-system | grep -F -- "-name $NAME" >/dev/null; then
  echo "$NAME is already running" >&2
  exit 2
fi
for port in "$SSH_PORT" "$API_PORT" "$PROXY_PORT"; do
  if ss -ltn "sport = :$port" | grep -q LISTEN; then
    echo "host port $port is already in use" >&2
    exit 2
  fi
done

test -f "$DISK" || qemu-img create -q -f qcow2 -b "$BASE" -F qcow2 "$DISK" 200G
if test ! -f "$SEED"; then
  BOXKEY=$(cat "$HOME/.ssh/id_ed25519_box.pub")
  CATKEY=$(head -1 "$HOME/.ssh/authorized_keys")
  printf '#cloud-config\nhostname: %s\nssh_authorized_keys:\n  - %s\n  - %s\npackage_update: false\nruncmd:\n  - apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y linux-modules-extra-$(uname -r) libgomp1\n' \
    "$NAME" "$BOXKEY" "$CATKEY" > "$VMS/$NAME-user-data"
  printf 'instance-id: %s\n' "$NAME" > "$VMS/$NAME-meta-data"
  cloud-localds "$SEED" "$VMS/$NAME-user-data" "$VMS/$NAME-meta-data"
fi

for artifact in "$VMS/$NAME-serial.log" "$VMS/$NAME-monitor.sock" "$VMS/$NAME.pid"; do
  if test -e "$artifact"; then
    sudo mv "$artifact" "$artifact.$(date -u +%Y%m%dT%H%M%SZ)"
  fi
done

echo "launching $NAME: SNP, $CPUS vCPU, $RAM RAM; ssh=$SSH_PORT api=$API_PORT"
sudo "$QEMU" \
  -name "$NAME" -enable-kvm -smp "$CPUS" -m "$RAM" \
  -machine 'q35,confidential-guest-support=sev0,memory-backend=ram0,kernel-irqchip=split' \
  -object "memory-backend-memfd,id=ram0,size=$RAM,share=true,prealloc=false" \
  -object 'sev-snp-guest,id=sev0,policy=0x30000,cbitpos=51,reduced-phys-bits=1' \
  -bios "$BIOS" -cpu host \
  -drive "file=$DISK,if=virtio,format=qcow2" \
  -drive "file=$SEED,if=virtio,format=raw,readonly=on" \
  -drive "file=$SMALL_MODELS,if=virtio,format=raw,readonly=on" \
  -drive "file=$GLM_MODELS,if=virtio,format=raw,readonly=on" \
  -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:$SSH_PORT-:22,hostfwd=tcp:127.0.0.1:$API_PORT-:8477,hostfwd=tcp:127.0.0.1:$PROXY_PORT-:8480" \
  -device virtio-net-pci,netdev=net0 \
  -display none -serial "file:$VMS/$NAME-serial.log" \
  -monitor "unix:$VMS/$NAME-monitor.sock,server,nowait" \
  -daemonize -pidfile "$VMS/$NAME.pid"

echo "started $NAME; existing guests were not changed"
