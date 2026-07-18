#!/usr/bin/env bash
# Run on the Sunburst host after snp-serve is shut down. Clone its guest disk
# and boot the same QEMU/OVMF/CPU/RAM/model image without confidential-guest
# support. This is the matched SEV-off twin for the full SNP inference sweep.
set -euo pipefail

QEMU="$HOME/src/AMDSEV/usr/local/bin/qemu-system-x86_64"
VMS="$HOME/vms"
SOURCE="$VMS/snp-serve.qcow2"
DISK="$VMS/snp-plain-twin.qcow2"
PIDFILE="$VMS/snp-plain-twin.pid"

if pgrep -f 'qemu-system-x86_64.*-name snp-serve' >/dev/null; then
  echo "FATAL: shut down snp-serve before cloning its disk" >&2
  exit 2
fi
if [ -f "$PIDFILE" ] && sudo kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "FATAL: snp-plain-twin is already running" >&2
  exit 3
fi

sudo rm -f "$DISK" "$VMS/snp-plain-twin-serial.log"
sudo qemu-img convert -p -O qcow2 "$SOURCE" "$DISK"

sudo "$QEMU" \
  -name snp-plain-twin -enable-kvm -smp 32 -m 64G \
  -machine "q35,memory-backend=ram0,kernel-irqchip=split" \
  -object "memory-backend-memfd,id=ram0,size=64G,share=true,prealloc=false" \
  -bios "$VMS/OVMF-snp.fd" -cpu host \
  -drive "file=$DISK,if=virtio,format=qcow2" \
  -drive "file=$VMS/snp-serve-seed.img,if=virtio,format=raw,readonly=on" \
  -drive "file=$VMS/models.img,if=virtio,format=raw,readonly=on" \
  -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:2223-:22" \
  -device virtio-net-pci,netdev=net0 \
  -display none -serial "file:$VMS/snp-plain-twin-serial.log" \
  -monitor "unix:$VMS/snp-plain-twin-monitor.sock,server,nowait" \
  -daemonize -pidfile "$PIDFILE"

echo "plain twin started: ssh -p 2223 ubuntu@127.0.0.1"
