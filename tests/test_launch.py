from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from server import registry
from server import main as server_main
from server.launch import launch_command, runtime_environment
from server.runtimes.base import Runtime


class RegistryLaunchTests(unittest.TestCase):
    def test_registry_rejects_duplicate_ids_and_ports(self):
        original = yaml.safe_load(registry.REGISTRY_PATH.read_text())
        cases = []
        duplicate_id = [dict(entry) for entry in original]
        duplicate_id[1]["id"] = duplicate_id[0]["id"]
        cases.append((duplicate_id, "duplicate model id"))
        duplicate_port = [dict(entry) for entry in original]
        duplicate_port[1]["port"] = duplicate_port[0]["port"]
        cases.append((duplicate_port, "duplicate runtime port"))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models.yaml"
            for payload, message in cases:
                path.write_text(yaml.safe_dump(payload, sort_keys=False))
                with (
                    self.subTest(message=message),
                    self.assertRaisesRegex(ValueError, message),
                ):
                    registry.load(path)

    def test_launcher_consumes_registry_fields(self):
        models = registry.load()
        bitnet = launch_command(models["bitnet-2b"], threads=32, context_cap=16_384)
        glm = launch_command(models["glm-5.2-q4"], threads=32, context_cap=16_384)

        self.assertIn(models["bitnet-2b"].weights, bitnet)
        self.assertIn(str(models["bitnet-2b"].port), bitnet)
        self.assertEqual(bitnet[bitnet.index("-c") + 1], "4096")
        self.assertNotIn("--jinja", bitnet)
        self.assertIn("--log-disable", bitnet)

        self.assertIn(models["glm-5.2-q4"].weights, glm)
        self.assertIn(str(models["glm-5.2-q4"].port), glm)
        self.assertEqual(glm[glm.index("-c") + 1], "16384")
        self.assertIn("--jinja", glm)
        self.assertIn("--log-disable", glm)

    def test_runtime_environment_prefers_binary_adjacent_libraries(self):
        model = registry.load()["bitnet-2b"]
        environment = runtime_environment(model)
        self.assertEqual(
            environment["LD_LIBRARY_PATH"].split(":", 1)[0],
            str(Path(launch_command(model, 32, 4096)[0]).parent),
        )

    def test_adapter_contract_has_required_operations(self):
        for method in ("load", "tokenize", "stream_generate"):
            self.assertTrue(hasattr(Runtime, method), method)

    def test_attestation_binding_uses_complete_hash_bearing_registry(self):
        models = registry.load()
        expected_ids = {model.id for model in models.values() if model.servable}
        pairs = server_main._registry_pairs()

        self.assertEqual({pair["id"] for pair in pairs}, expected_ids)
        self.assertEqual(registry.pairs_hash(pairs), registry.registry_hash(models))


if __name__ == "__main__":
    unittest.main()
