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
