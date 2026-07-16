#!/usr/bin/env bash
# Launch a measurement VM (run ON the box). Legs A and B use IDENTICAL shapes;
# the ONLY difference is --sev snp vs --sev off (fair-comparison rule).
#
# Usage: ./launch-vm.sh --name legA --sev off  --cpus 64 --ram 256G --ssh-port 2201
#        ./launch-vm.sh --name legB --sev snp  --cpus 64 --ram 256G --ssh-port 2202
set -euo pipefail

QEMU="$HOME/src/qemu-9.2.4/build/qemu-system-x86_64"
OVMF_CODE=/usr/share/OVMF/OVMF_CODE_4M.fd
IMG_BASE="$HOME/vms/noble-server-cloudimg-amd64.img"
VMS="$HOME/vms"
mkdir -p "$VMS"

NAME=vm; SEV=off; CPUS=64; RAM=256G; SSH_PORT=2201
while [ $# -gt 0 ]; do case "$1" in
  --name) NAME="$2"; shift 2;; --sev) SEV="$2"; shift 2;;
  --cpus) CPUS="$2"; shift 2;; --ram) RAM="$2"; shift 2;;
  --ssh-port) SSH_PORT="$2"; shift 2;; *) echo "unknown arg $1"; exit 1;;
esac; done

# base cloud image (download once)
if [ ! -f "$IMG_BASE" ]; then
  curl -fL -o "$IMG_BASE" \
    https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
fi

DISK="$VMS/$NAME.qcow2"
if [ ! -f "$DISK" ]; then
  qemu-img create -q -f qcow2 -b "$IMG_BASE" -F qcow2 "$DISK" 200G
fi

# cloud-init seed: inject the box's automation pubkey + Cat's sunburst pubkey
SEED="$VMS/$NAME-seed.img"
if [ ! -f "$SEED" ]; then
  [ -f "$HOME/.ssh/id_ed25519_box" ] || ssh-keygen -q -t ed25519 -N "" -f "$HOME/.ssh/id_ed25519_box"
  BOXKEY=$(cat "$HOME/.ssh/id_ed25519_box.pub")
  CATKEY=$(head -1 "$HOME/.ssh/authorized_keys")
  cat > "$VMS/$NAME-user-data" <<EOF
#cloud-config
hostname: $NAME
ssh_authorized_keys:
  - $BOXKEY
  - $CATKEY
package_update: false
EOF
  echo "instance-id: $NAME" > "$VMS/$NAME-meta-data"
  cloud-localds "$SEED" "$VMS/$NAME-user-data" "$VMS/$NAME-meta-data"
fi

VARS="$VMS/$NAME-OVMF_VARS.fd"
[ -f "$VARS" ] || cp /usr/share/OVMF/OVMF_VARS_4M.fd "$VARS"

BASE=(
  -name "$NAME" -enable-kvm -cpu host -smp "$CPUS" -m "$RAM"
  -drive "file=$DISK,if=virtio,format=qcow2"
  -drive "file=$SEED,if=virtio,format=raw,readonly=on"
  -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:$SSH_PORT-:22" -device virtio-net-pci,netdev=net0
  -display none -serial "file:$VMS/$NAME-serial.log" -monitor "unix:$VMS/$NAME-monitor.sock,server,nowait"
  -daemonize -pidfile "$VMS/$NAME.pid"
)

if [ "$SEV" = "snp" ]; then
  # SNP CVM: memfd-backed memory, cbitpos=51 (Zen4/Zen5), -bios instead of
  # pflash (SNP guests do not support KVM readonly pflash).
  echo "launching $NAME (SEV-SNP, $CPUS vCPU, $RAM) ssh port $SSH_PORT"
  sudo "$QEMU" \
    -machine "q35,confidential-guest-support=sev0,memory-backend=ram0" \
    -object "memory-backend-memfd,id=ram0,size=$RAM,share=true" \
    -object "sev-snp-guest,id=sev0,cbitpos=51,reduced-phys-bits=1" \
    -bios /usr/share/ovmf/OVMF.fd \
    "${BASE[@]}"
else
  echo "launching $NAME (no SEV, $CPUS vCPU, $RAM) ssh port $SSH_PORT"
  sudo "$QEMU" -machine q35 \
    -drive "if=pflash,format=raw,unit=0,file=$OVMF_CODE,readonly=on" \
    -drive "if=pflash,format=raw,unit=1,file=$VARS" \
    "${BASE[@]}"
fi
echo "started. serial: $VMS/$NAME-serial.log · ssh (from box): ssh -p $SSH_PORT ubuntu@127.0.0.1"
