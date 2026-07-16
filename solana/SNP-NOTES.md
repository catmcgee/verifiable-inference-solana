# SEV-SNP guest (CVM) — boot, attestation, and tax notes

Session date: 2026-07-16. Host: AMD EPYC 9555P (Zen5 / Turin), 128 threads, 1.13 TiB RAM,
kernel 6.17 with `kvm_amd: SEV-SNP enabled (ASIDs 1-99)`, SEV-SNP API 1.55.

## Does it boot? YES.

A real SEV-SNP guest (CVM) boots to a login shell over SSH. Inside the guest `dmesg`
shows:

```
Memory Encryption Features active: AMD SEV SEV-ES SEV-SNP
SEV: Using SNP CPUID table, 38 entries present.
SEV: SNP guest platform device initialized.
```

`/dev/sev-guest` is present (after `modprobe sev-guest`, provided by
`linux-modules-extra-6.8.0-134-generic`, installed in-guest).

## What combo worked

The blocker was the **guest firmware (OVMF)**, not QEMU and not the `-cpu` model.

- Steps that FAILED, all with the identical firmware-time error
  `Convert non guest_memfd backed memory region (0xfee00000,+0x1000) to private`
  (the APIC MMIO page):
  - distro QEMU 10.2.4 + `/usr/share/ovmf/OVMF.amdsev.fd`, `-cpu host` (retry of prior EPYC-v4 failure)
  - **AMDSEV-built QEMU (snp-latest, v10.0.0)** + the same old `OVMF.amdsev.fd`
  This proves the fix lives in the OVMF binary (SNP legacy-ROM / APIC page in
  guest_memfd support), not the QEMU version.

- The combo that WORKS:
  - **QEMU:** `~/src/AMDSEV/usr/local/bin/qemu-system-x86_64` (AMDESE qemu `snp-latest`, 10.0.0)
  - **OVMF:** freshly built from edk2 (AMDSEV `ovmf/` tree) → `~/vms/OVMF-snp.fd`
    (copied from `ovmf/Build/OvmfX64/DEBUG_GCC/FV/OVMF.fd`)
  - **Build gotcha:** AMDSEV `./build.sh ovmf` FAILS on this box — edk2 master has
    dropped the `GCC5` toolchain tag, but `common.sh` hardcodes it, giving
    `build.py error 4000: [GCC5] not defined. No toolchain available for build!`
    Fix: build OVMF manually with the current `GCC` tag:
    `cd ~/src/AMDSEV/ovmf && source ./edksetup.sh --reconfig && build -t GCC -a X64 -p OvmfPkg/OvmfPkgX64.dsc`
    (BaseTools were already built by the failed run.) QEMU built fine via `./build.sh qemu`.

- Launch flags (see `~/launch-snp.sh` and inline command in session log):
  `-machine q35,confidential-guest-support=sev0,memory-backend=ram0,kernel-irqchip=split`
  `-object memory-backend-memfd,id=ram0,size=RAM,share=true,prealloc=false`
  `-object sev-snp-guest,id=sev0,policy=0x30000,cbitpos=51,reduced-phys-bits=1`
  `-bios ~/vms/OVMF-snp.fd -cpu host` (no pflash — SNP uses stateless `-bios`).
  cbitpos=51 for Zen4/Zen5. Guest kernel: stock noble `6.8.0-134-generic`.

## snpguest report status: REAL and KDS-VERIFIABLE

`snpguest 0.10.0` (static binary, `~/vms/snpguest`) run inside the guest produced a
genuine 1184-byte SNP attestation report from the PSP (~0.02 s):
`~/vms/snp-report.bin` (sha256 b703eb7ab68b3b042da382e702a37f569c80c161b3fa4fafe3029695a9e9bfec).

Report highlights: Version 5, VMPL 1, Guest Policy 0x30000 (SMT allowed, debug
disabled), Current TCB microcode 71 / SNP 2 / boot-loader 1.

Verification against AMD Key Distribution Service (KDS), Turin cert chain:

```
verify certs:        The AMD ARK was self-signed!
                     The AMD ASK was signed by the AMD ARK!
                     The VCEK was signed by the AMD ASK!
verify attestation:  Reported TCB (BL/TEE/SNP/Microcode/FMC) matches the report.
                     VEK signed the Attestation Report!
```

Full chain of trust: ARK (self-signed root) → ASK → VCEK (fetched from KDS by
chip-id/TCB) → report signature. This is what makes leg B attestation-grade
**"snp"** rather than **"es"** — SEV-ES has no hardware attestation report.

## Tax: STREAM (memory bandwidth)

STREAM Triad, 32 threads, 32 vCPU / 64 GiB guest, `~/vms/stream.bin` (same binary/shape
as the earlier ES run). Full canonical output in `~/vms/snp-stream.txt`.

| config    | Triad GB/s |
|-----------|------------|
| plain-VM  | 346.19  (prior session, runs/legAB-stream.jsonl) |
| SEV-ES    | 256.10  (prior session, runs/legAB-stream.jsonl) |
| **SEV-SNP** | **376.91** (this session, warm canonical run) |

Caveats: SNP runs showed real cold→warm variance (315 → 320 → 346 → 366 → then a
stable plateau ~377–380 GB/s over repeated runs) because the host was concurrently
serving the vinfer/llama model servers (ports 8477, 8601-8605), which contend for
memory bandwidth. Host load stayed low (0.3–1.0). The plain-VM/ES baselines were
measured in an earlier session under unknown host conditions, so cross-config
absolute comparison is only indicative. **Takeaway: SNP memory bandwidth is in the
same class as a plain VM (no meaningful SNP memory-bandwidth tax observed); the
recorded ES 256 number looks anomalously low relative to both.**

Session record (schema-valid vs harness/session_schema.json):
`~/verified-inference/runs/snp-results.jsonl` →
`legB-snpcvm-snp, sev_mode=snp, boot_s=4.838 (kernel), first_attestation_s=0.02, stream_triad_gbs=376.91`.

## Tax: inference (directional)

Ran all three models with `llama-bench` (32 threads, -p 16 -n 128) inside the SNP
guest against `models.img`. Raw results in `~/vms/snp-inference-bench.txt`:

| model      | SNP tg128 t/s | A(off) median | ES median | notes |
|------------|---------------|---------------|-----------|-------|
| bitnet-2b  | 199.14 | 148.65 | 153.06 | not comparable — see below |
| 8b-q4      | 68.60  | 70.80  | 69.40  | SNP ~3% below plain-VM |
| 70b-q4     | 9.50   | 9.69   | 9.51   | SNP within ~0.1% |

**Important:** these SNP numbers are raw `llama-bench` (pure decode). The frozen
A/off and B/es medians in `runs/legAB-inference.jsonl` were produced by the TLS
`vinfer` harness (per-request TLS + server overhead). For compute-bound models
(8b, 70b) that overhead is negligible and the numbers line up almost exactly →
**no meaningful SNP inference tax**. For the tiny/fast bitnet model the harness
overhead is a large fraction of per-token time, so the raw-bench SNP number (199)
is HIGHER than the harness A/ES numbers (148/153); this is a protocol difference,
not an SNP speedup.

Because the protocols differ, these SNP inference numbers were **deliberately NOT
appended** to the frozen `legAB-inference.jsonl` / schema.json (doing so would put
non-comparable rows into frozen comparable data). They are recorded here and in
`~/vms/snp-inference-bench.txt` as directional. A fully protocol-matched leg-B/snp
inference run would require standing up the vinfer TLS server stack inside the CVM.

## Reproduce

`~/launch-snp.sh` (created this session) + `~/vms/OVMF-snp.fd`. Boot, then in-guest:
`sudo apt-get install -y linux-modules-extra-$(uname -r) libgomp1 && sudo modprobe sev-guest`.
