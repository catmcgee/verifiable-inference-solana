#!/usr/bin/env bash
# Recon gate. Runs the checklist on the box via `ssh sunburst`
# (Host alias must exist in your ~/.ssh/config — see infra/ssh_config) and
# captures raw output into recon/raw/. Read-only except for building STREAM
# in /tmp on the box. Safe to re-run.
set -uo pipefail

HOST="${1:-sunburst}"
OUT="$(cd "$(dirname "$0")" && pwd)/raw"
mkdir -p "$OUT"

run() { # run <name> <remote command>
  local name="$1"; shift
  echo "── $name"
  ssh "$HOST" "$@" >"$OUT/$name.txt" 2>&1
  echo "   exit=$? → recon/raw/$name.txt"
}

echo "recon target: $HOST ($(date -u +%FT%TZ))" | tee "$OUT/00_meta.txt"
ssh -o ConnectTimeout=10 "$HOST" true || { echo "cannot ssh to '$HOST' — fix ~/.ssh/config first"; exit 1; }

# 0. who else is here (standing rule: box may be shared)
run 00_who 'who; uptime; ps aux --sort=-%cpu | head -15'

# 1. CPU + SEV surface
run 01_lscpu 'lscpu'
run 02_cpuinfo_sev 'grep -m1 -o "sev[a-z_]*" /proc/cpuinfo; grep -c processor /proc/cpuinfo'
run 03_dmesg_sev 'sudo -n dmesg 2>/dev/null | grep -i -E "sev|snp|ccp" || dmesg 2>/dev/null | grep -i -E "sev|snp|ccp" || echo "dmesg unreadable without sudo"'
run 04_kernel_params 'cat /proc/cmdline; ls /sys/module/kvm_amd/parameters/ 2>/dev/null && grep -r . /sys/module/kvm_amd/parameters/ 2>/dev/null'

# 2. SNP guest role
run 05_sev_guest_dev 'ls -la /dev/sev-guest 2>&1; ls -la /sys/devices/platform/sev-guest 2>&1'
run 06_snpguest 'command -v snpguest && snpguest ok 2>&1 || echo "snpguest not installed"'
run 07_dmi 'sudo -n dmidecode -t system 2>/dev/null || cat /sys/class/dmi/id/product_name /sys/class/dmi/id/sys_vendor 2>/dev/null'

# 3. SNP host role
run 08_sev_host_dev 'ls -la /dev/sev 2>&1'
run 09_sevctl 'command -v sevctl && sevctl ok 2>&1 || echo "sevctl not installed"'
run 10_kvm 'ls -la /dev/kvm 2>&1; command -v qemu-system-x86_64 && qemu-system-x86_64 --version || echo "qemu not installed"'

# 4. Topology / resources
run 11_gpu 'command -v nvidia-smi && nvidia-smi || echo "no nvidia-smi (expected)"; lspci 2>/dev/null | grep -i -E "nvidia|display|3d" || true'
run 12_numa 'command -v numactl && numactl -H || echo "numactl not installed"'
run 13_mem_disk 'free -h; df -h; lsblk'
run 14_os 'uname -a; cat /etc/os-release; cat /sys/devices/system/cpu/vulnerabilities/* 2>/dev/null | sort -u'

# 5. STREAM triad quick run (build in /tmp on the box)
run 15_stream 'set -e; cd /tmp; if [ ! -x stream_c ]; then
  curl -fsSL -o stream.c https://raw.githubusercontent.com/jeffhammond/STREAM/master/stream.c &&
  (command -v gcc && gcc -O3 -fopenmp -DSTREAM_ARRAY_SIZE=400000000 -DNTIMES=10 -mcmodel=large stream.c -o stream_c) || echo "no gcc — record and move on"; fi
  [ -x stream_c ] && OMP_NUM_THREADS=$(nproc) ./stream_c || true'

echo
echo "done. Raw output in recon/raw/. Next: distill into recon/findings.md and pick the decision-table row."
