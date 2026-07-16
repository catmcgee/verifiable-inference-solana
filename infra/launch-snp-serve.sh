#!/usr/bin/env bash
# SNP guest launcher (attempt series). Args: --name --cpu (host|EPYC-v4) --qemu PATH --bios PATH --cpus N --ram SIZE --ssh-port P
set -euo pipefail
QEMU="$HOME/src/AMDSEV/usr/local/bin/qemu-system-x86_64"
BIOS=$HOME/vms/OVMF-snp.fd
IMG_BASE="$HOME/vms/noble-server-cloudimg-amd64.img"
VMS="$HOME/vms"
NAME=snp-host; CPU=host; CPUS=32; RAM=64G; SSH_PORT=2222
while [ $# -gt 0 ]; do case "$1" in
  --name) NAME="$2"; shift 2;; --cpu) CPU="$2"; shift 2;;
  --qemu) QEMU="$2"; shift 2;; --bios) BIOS="$2"; shift 2;;
  --cpus) CPUS="$2"; shift 2;; --ram) RAM="$2"; shift 2;;
  --ssh-port) SSH_PORT="$2"; shift 2;; *) echo "unknown arg $1"; exit 1;;
esac; done
DISK="$VMS/$NAME.qcow2"
[ -f "$DISK" ] || qemu-img create -q -f qcow2 -b "$IMG_BASE" -F qcow2 "$DISK" 200G
SEED="$VMS/$NAME-seed.img"
if [ ! -f "$SEED" ]; then
  BOXKEY=$(cat "$HOME/.ssh/id_ed25519_box.pub")
  CATKEY=$(head -1 "$HOME/.ssh/authorized_keys")
  printf "#cloud-config\nhostname: %s\nssh_authorized_keys:\n  - %s\n  - %s\npackage_update: false\n" "$NAME" "$BOXKEY" "$CATKEY" > "$VMS/$NAME-user-data"
  echo "instance-id: $NAME" > "$VMS/$NAME-meta-data"
  cloud-localds "$SEED" "$VMS/$NAME-user-data" "$VMS/$NAME-meta-data"
fi
echo "launching $NAME (SEV-SNP, cpu=$CPU, $CPUS vCPU, $RAM) qemu=$QEMU bios=$BIOS ssh port $SSH_PORT"
sudo rm -f "$VMS/$NAME-serial.log"
sudo "$QEMU" \
  -name "$NAME" -enable-kvm -smp "$CPUS" -m "$RAM" \
  -machine "q35,confidential-guest-support=sev0,memory-backend=ram0,kernel-irqchip=split" \
  -object "memory-backend-memfd,id=ram0,size=$RAM,share=true,prealloc=false" \
  -object "sev-snp-guest,id=sev0,policy=0x30000,cbitpos=51,reduced-phys-bits=1" \
  -bios "$BIOS" -cpu "$CPU" \
  -drive "file=$DISK,if=virtio,format=qcow2" \
  -drive "file=$SEED,if=virtio,format=raw,readonly=on" \
  -drive "file=$VMS/models.img,if=virtio,format=raw,readonly=on" \
  -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:$SSH_PORT-:22,hostfwd=tcp:127.0.0.1:8478-:8477" -device virtio-net-pci,netdev=net0 \
  -display none -serial "file:$VMS/$NAME-serial.log" -monitor "unix:$VMS/$NAME-monitor.sock,server,nowait" \
  -daemonize -pidfile "$VMS/$NAME.pid"
echo "started."
