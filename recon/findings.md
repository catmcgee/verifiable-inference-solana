# P1 Recon findings — instance `cat-verif` (dashboard) / hostname `cat-verif-ai`

Recon run 2026-07-16 via `recon/run_recon.sh` (raw output in `recon/raw/`).
Access: `ssh sunburst` → 213.239.141.40, user `ubuntu`, Ubuntu 24.04 LTS
(noble). Provisioned from sunburst.monogon.dev, project "Cat".

> **CURRENT STATE (verified live on the box, superseding the original headline
> below).** Kernel is now **`6.17.0-40-generic`** (HWE), not 6.8. SEV, SEV-ES,
> **and SEV-SNP are all enabled at the HOST**: CPU flags `sev sev_es sev_snp`,
> `/dev/sev` present, `/sys/module/kvm_amd/parameters/sev_snp=Y`. `/dev/sev-guest`
> is absent (this is the host, not a guest). Decision-table row achieved:
> **Row 1 host-control. SNP guests now boot** with the matched AMDSEV OVMF/QEMU
> path, produce VMPL0 reports, and serve all four measured local models. The
> current public boot is `grade=snp` and verifies report -> VCEK -> ASK/ARK;
> exact cloned-disk plain/SNP inference results live in
> `runs/legA-snp-twin-full.jsonl` and `runs/legB-snp-single-full.jsonl`.
> The older SEV-ES data remains a distinct historical experiment and is still
> labeled `launch-only`; it is not relabeled or pooled with the SNP twin.
> STREAM both SEV states: SEV-off (plain VM) 346.19 GB/s vs SEV-ES 256.10 GB/s =
> **26.0% bandwidth tax** (`runs/legAB-stream.jsonl`; the SEV-off-only baseline
> below, 357.1 GB/s bare-metal 128t, is a separate anchor — do not pool them).
> The original text below is kept for history; it is STALE.

## (STALE, session-2) Headline: we got the BARE-METAL HOST, and SEV is disabled in BIOS

This is not a VM. Evidence:

- Full hardware surface: AMD PSP/CCP device visible (`ccp 0000:a1:00.5: psp
  enabled` in dmesg), real SMBIOS (fields "To be filled by O.E.M."), all 128
  threads of the EPYC 9555P, 1.13 TiB RAM, single NUMA node.
- `/dev/kvm` exists and `kvm_amd` is loaded with full parameter surface
  (avic, nested, npt, sev/sev_es params present) — we can launch VMs.
- No hypervisor flag in cpuinfo; no `/dev/sev-guest` (we're not a guest).

**But:** `dmesg`: `ccp 0000:a1:00.5: SEV: memory encryption not enabled by
BIOS`, `/dev/sev` absent, and no `sme/sev/sev_es/sev_snp` CPU flags — the
BIOS has SMEE (memory encryption) turned off, which hides the entire SEV
feature family. `svm` is present, so plain virtualization works fine.

## Decision table row

**UPDATE 2026-07-16 (session 3): BIOS fully SNP-ready; SEV+SEV-ES LIVE; SNP blocked on kernel.**
Two BIOS passes via serial console set: SMEE=Enable, SEV Control=Enable,
**SEV-ES ASID Space Limit=100**, **SNP Memory (RMP Table) Coverage=Enabled**.
Post-reboot: `kvm_amd: SEV enabled (ASIDs 100-1006)`, `SEV-ES enabled
(ASIDs 1-99)`, `/dev/sev` present, flags `sme sev sev_es`. **SEV + SEV-ES work.**
SNP NOT active: no `sev_snp` flag, no RMP dmesg, `/sys/module/kvm_amd/
parameters/sev_snp` absent. **Root cause = kernel 6.8.0 < 6.11** (KVM SNP host
support merged upstream in 6.11). BIOS side is complete; SNP needs a newer
kernel (Ubuntu HWE / mainline 6.11+ / AMD SNP host branch). No more BIOS work.

Originally **Row 4 — "SEV disabled in BIOS"** (memory encryption not enabled).
Target remains **Row 1 — "Host control + SNP capable"**: we launch BOTH legs
ourselves — leg A = non-SEV VM, leg B = SNP CVM, identical shape, differ ONLY
in SEV state, full SNP → AMD KDS verifiability.

Meanwhile NOT blocked: leg A serving (P2) on bare metal + in a plain VM,
leg C (Claude proxy), leg D (zkML ladder), Solana devnet receipts.

## Inventory

| Item | Found |
|---|---|
| CPU | AMD EPYC 9555P, 64C/128T, flags incl. avx512f/bf16/vnni, vaes, sha_ni |
| RAM | 1,160,226 MB (1.13 TiB), single NUMA node (NPS1), ~1.12 TiB free |
| Disk | KIOXIA CD8P-V NVMe (6.4 TB class) |
| GPU | None (confirmed: no nvidia-smi, no NVIDIA on lspci) |
| Virt | /dev/kvm present; qemu NOT installed yet (apt-installable) |
| SEV tooling | snpguest/sevctl not installed (install when BIOS enables SEV) |
| Mitigations | eIBRS etc. active — record with every run; keep constant A vs B |

## STREAM triad anchor (SEV off — the baseline number)

gcc -O3 -fopenmp, 400M elements, 128 threads, first quick run:

| Kernel | Best rate |
|---|---|
| Copy | 312.2 GB/s |
| Scale | 310.5 GB/s |
| Add | 355.0 GB/s |
| **Triad** | **357.1 GB/s** |

~58% of the 614 GB/s theoretical. Notes: quick untuned build (no
non-temporal-store tuning, no per-CCD pinning, transparent hugepages
default). Good enough as the v0 anchor; tune before the headline A/B
comparison and ALWAYS use the identical binary+flags in both SEV states.
NPS1 (single NUMA node) means no NUMA policy dimension on bare metal —
record `numa_policy: "nps1-default"`.

## Actions

1. **Cat → Tim/Monogon:** enable SMEE/SEV/SEV-ES/SEV-SNP in BIOS for this
   box (or a per-instance TEE option in the dashboard if that exists).
   Also ask: is the E2100 IPU in the trust path for anything?
2. P2 proceeds now on bare metal (leg A) — install runtimes, download models.
3. Install qemu/OVMF + snpguest/sevctl when the BIOS change lands.
