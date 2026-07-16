#!/usr/bin/env bash
# Build QEMU with SEV-SNP guest-launch support (run ON the box).
# Ubuntu 24.04 ships qemu 8.2; the sev-snp-guest object needs QEMU >= 9.1.
set -euo pipefail
QV=9.2.4
SRC="$HOME/src"
mkdir -p "$SRC"

sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  ninja-build meson libglib2.0-dev libpixman-1-dev flex bison \
  libslirp-dev libcap-ng-dev libattr1-dev zlib1g-dev python3-venv >/dev/null

if [ ! -x "$SRC/qemu-$QV/build/qemu-system-x86_64" ]; then
  cd "$SRC"
  [ -f "qemu-$QV.tar.xz" ] || curl -fLO "https://download.qemu.org/qemu-$QV.tar.xz"
  [ -d "qemu-$QV" ] || tar xf "qemu-$QV.tar.xz"
  cd "qemu-$QV"
  ./configure --target-list=x86_64-softmmu --enable-kvm --enable-slirp >/dev/null
  make -j"$(nproc)" >/dev/null
fi
"$SRC/qemu-$QV/build/qemu-system-x86_64" --version
"$SRC/qemu-$QV/build/qemu-system-x86_64" -object help 2>/dev/null | grep -i sev || true
echo "qemu build done."
