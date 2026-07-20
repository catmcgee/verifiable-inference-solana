# Measured immutable guest

This pipeline closes the mutable-userspace gap in the legacy SNP guest.

`build-on-host.sh` clones the current guest into a read-only ext4 root, installs
an initramfs dm-verity gate, verifies every registry weight against
`models.yaml`, builds separate dm-verity trees for root and model images, and
records only public artifact hashes. `launch.sh` uses QEMU SNP measured direct
boot with `kernel-hashes=on`; the measured command line carries every verity
root. The guest has no SSH listener or QEMU monitor, and model/API services run
from verified read-only filesystems.

At boot, trusted root code derives `/run/vinfer/boot-evidence.json`. The server
adds its runtime version and registry hash, canonicalizes that execution
manifest, and binds its SHA-256 as `server_build_hash` in REPORT_DATA. Client
policy must approve the exact `(SNP measurement, server_build_hash,
execution_mode)` tuple. A hash in an independently mutable guest is not enough.

This proves which inspected code and model image could use the attested signing
key. It does not prove mathematical correctness of every output, eliminate AMD
or operator availability trust, or prevent all side channels.

## Production operation

`vinfer-measured-vm.service` is the only public TEE VM. It launches the approved
artifact prefix on loopback ports 8479 and 8482 with all five registry models.
`vinfer-builder-vm.service` runs the former mutable guest with 64 GiB of memory
and SSH on loopback port 2223. It is a build source only and is never routed by
Caddy.

TEE runtime changes are deliberately not hot-restarted from a Git push. CI
syncs audited source to the host and builder, then reports that a measured image
promotion is required. Promotion consists of:

1. Build a new, uniquely named artifact prefix with `build-on-host.sh`.
2. Verify its root and model hashes, then launch it without public traffic.
3. Verify the SNP report and execution manifest, approve the exact
   `(measurement, server_build_hash, execution_mode)` tuple, and register the
   boot key on Solana devnet.
4. Point `/etc/vinfer/measured-vm` at the approved prefix and restart the
   production VM service.

The frontend, Caddy, receipt relay, and no-TEE baseline still deploy normally.
This promotion boundary is required: automatically accepting an arbitrary new
root hash would make the immutable execution proof meaningless.
