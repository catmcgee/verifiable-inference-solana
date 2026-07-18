from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.execution import load_identity


class ExecutionIdentityTests(unittest.TestCase):
    def test_legacy_identity_is_explicitly_guest_declared(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            identity = load_identity("vinfer-test")
        self.assertEqual(identity.mode, "guest-declared")
        self.assertEqual(identity.build_hash, hashlib.sha256(b"vinfer-test").digest())
        self.assertIsNone(identity.manifest)

    def test_manifest_hash_is_canonical_and_registry_is_checked(self) -> None:
        registry_hash = hashlib.sha256(b"registry").hexdigest()
        manifest = {
            "schema_version": 1,
            "mode": "snp-measured-dm-verity",
            "runtime_version": "vinfer-test",
            "registry_hash": registry_hash,
            "kernel_sha256": "11" * 32,
            "initrd_sha256": "22" * 32,
            "cmdline_sha256": "33" * 32,
            "root_verity_hash": "44" * 32,
            "model_verity_hashes": {"models": "55" * 32},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest, indent=2))
            with patch.dict(os.environ, {"VINFER_EXECUTION_MANIFEST": str(path)}):
                identity = load_identity("vinfer-test")
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(identity.build_hash, hashlib.sha256(canonical).digest())
        identity.validate_registry(bytes.fromhex(registry_hash))
        with self.assertRaisesRegex(RuntimeError, "models.yaml"):
            identity.validate_registry(bytes(32))

    def test_boot_evidence_is_completed_with_runtime_and_registry(self) -> None:
        registry_hash = hashlib.sha256(b"registry").digest()
        evidence = {
            "kernel_sha256": "11" * 32,
            "initrd_sha256": "22" * 32,
            "cmdline_sha256": "33" * 32,
            "root_verity_hash": "44" * 32,
            "model_verity_hashes": {"models": "55" * 32},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(evidence))
            with patch.dict(
                os.environ, {"VINFER_BOOT_EVIDENCE": str(path)}, clear=True
            ):
                identity = load_identity("vinfer-test", registry_hash)
        self.assertEqual(identity.manifest["registry_hash"], registry_hash.hex())
        self.assertEqual(identity.manifest["runtime_version"], "vinfer-test")


if __name__ == "__main__":
    unittest.main()
