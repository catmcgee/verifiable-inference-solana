"""Execution identity bound into SNP REPORT_DATA.

Legacy deployments bind the runtime version string and are explicitly
guest-declared. A measured deployment supplies a canonical manifest whose hash
is the build hash. The launch policy must pair that hash with the exact SNP
measurement produced by QEMU measured direct boot.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BuildIdentity:
    runtime_version: str
    build_hash: bytes
    mode: str
    manifest: dict | None

    def validate_registry(self, registry_hash: bytes) -> None:
        if self.manifest is None:
            return
        declared = self.manifest.get("registry_hash")
        if declared != registry_hash.hex():
            raise RuntimeError(
                "execution manifest registry_hash does not match models.yaml"
            )

    def public_document(self) -> dict:
        return {
            "mode": self.mode,
            "manifest": self.manifest,
        }


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _validate_manifest(value: dict, runtime_version: str) -> None:
    required = {
        "schema_version",
        "mode",
        "runtime_version",
        "registry_hash",
        "kernel_sha256",
        "initrd_sha256",
        "cmdline_sha256",
        "root_verity_hash",
        "model_verity_hashes",
    }
    missing = sorted(required - value.keys())
    if missing:
        raise RuntimeError(f"execution manifest missing fields: {missing}")
    if value["schema_version"] != 1:
        raise RuntimeError("unsupported execution manifest schema_version")
    if value["mode"] != "snp-measured-dm-verity":
        raise RuntimeError("execution manifest mode must be snp-measured-dm-verity")
    if value["runtime_version"] != runtime_version:
        raise RuntimeError("execution manifest runtime_version mismatch")
    for field in (
        "registry_hash",
        "kernel_sha256",
        "initrd_sha256",
        "cmdline_sha256",
        "root_verity_hash",
    ):
        item = value[field]
        if not isinstance(item, str) or len(item) != 64:
            raise RuntimeError(
                f"execution manifest {field} must be a SHA-256 hex value"
            )
        bytes.fromhex(item)
    model_hashes = value["model_verity_hashes"]
    if not isinstance(model_hashes, dict) or not model_hashes:
        raise RuntimeError("execution manifest model_verity_hashes must be non-empty")
    for name, item in model_hashes.items():
        if not isinstance(name, str) or not isinstance(item, str) or len(item) != 64:
            raise RuntimeError("invalid model verity hash in execution manifest")
        bytes.fromhex(item)


def load_identity(
    runtime_version: str, registry_hash: bytes | None = None
) -> BuildIdentity:
    path_value = os.environ.get("VINFER_EXECUTION_MANIFEST")
    evidence_value = os.environ.get("VINFER_BOOT_EVIDENCE")
    if not path_value and not evidence_value:
        return BuildIdentity(
            runtime_version=runtime_version,
            build_hash=hashlib.sha256(runtime_version.encode()).digest(),
            mode="guest-declared",
            manifest=None,
        )

    path = Path(path_value or evidence_value or "")
    raw = path.read_bytes()
    if len(raw) > 64 * 1024:
        raise RuntimeError("execution manifest exceeds 64 KiB")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("execution manifest must be a JSON object")
    if evidence_value and not path_value:
        if registry_hash is None:
            raise RuntimeError("registry_hash is required with VINFER_BOOT_EVIDENCE")
        value = {
            **value,
            "schema_version": 1,
            "mode": "snp-measured-dm-verity",
            "runtime_version": runtime_version,
            "registry_hash": registry_hash.hex(),
        }
    _validate_manifest(value, runtime_version)

    canonical = _canonical(value)
    return BuildIdentity(
        runtime_version=runtime_version,
        build_hash=hashlib.sha256(canonical).digest(),
        mode="snp-measured-dm-verity",
        manifest=value,
    )
