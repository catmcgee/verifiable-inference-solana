from __future__ import annotations

import json
import shutil
import subprocess
import unittest

from jsonschema import Draft7Validator

from payskill.generate_runtime import runtime_spec
from server import registry


class PayRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.spec = runtime_spec(
            upstream="http://127.0.0.1:8477",
            network="localnet",
            max_request_usd=0.50,
        )

    def test_models_yaml_is_the_only_pricing_source(self):
        models = registry.load()
        paid = next(
            endpoint
            for endpoint in self.spec["endpoints"]
            if endpoint["path"] == "v1/chat/completions"
        )
        variants = {row["value"]: row for row in paid["metering"]["variants"]}
        expected = {
            model.id
            for model in models.values()
            if model.servable
            and model.price_per_1m_in_usdc is not None
            and model.price_per_1m_out_usdc is not None
        }
        self.assertEqual(set(variants), expected)
        for model_id, variant in variants.items():
            model = models[model_id]
            self.assertEqual(
                [
                    dimension["tiers"][0]["price_usd"]
                    for dimension in variant["dimensions"]
                ],
                [model.price_per_1m_in_usdc, model.price_per_1m_out_usdc],
            )

        rendered = json.dumps(self.spec)
        for model in models.values():
            self.assertNotIn(model.weights, rendered)

    def test_paid_route_uses_official_gateway_and_origin_auth(self):
        paid = next(
            endpoint
            for endpoint in self.spec["endpoints"]
            if endpoint["path"] == "v1/chat/completions"
        )
        self.assertEqual(paid["metering"]["schemes"], ["x402-upto"])
        self.assertEqual(paid["metering"]["upto"]["missing_usage"], "error")
        self.assertIn("stream=false", paid["description"])
        self.assertEqual(
            self.spec["routing"]["auth"],
            {
                "method": "header",
                "key": "Authorization",
                "prefix": "Bearer ",
                "value_from_env": "VINFER_ORIGIN_TOKEN",
            },
        )

    @unittest.skipUnless(shutil.which("pay"), "pay CLI is not installed")
    def test_current_pay_schema_accepts_generated_spec(self):
        result = subprocess.run(
            ["pay", "docs", "schema"],
            check=True,
            capture_output=True,
            text=True,
        )
        errors = list(Draft7Validator(json.loads(result.stdout)).iter_errors(self.spec))
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
