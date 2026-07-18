"""Run an actual pay CLI sandbox payment through the generated proxy spec."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from payskill.generate_runtime import write_runtime


ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://127.0.0.1:18477"
GATEWAY = "http://127.0.0.1:11402"
ORIGIN_TOKEN = "test-origin-token-for-local-pay-gateway"


def wait_for(url: str, timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=1).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise TimeoutError(f"timed out waiting for {url}")


def stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> None:
    if shutil.which("pay") is None:
        raise SystemExit("pay CLI is required for the sandbox integration test")
    with tempfile.TemporaryDirectory(prefix="vinfer-pay-") as directory:
        runtime = Path(directory) / "inference.yaml"
        write_runtime(
            runtime,
            upstream=ORIGIN,
            network="localnet",
            max_request_usd=0.50,
        )
        origin = subprocess.Popen(
            [
                "uv",
                "run",
                "uvicorn",
                "tests.mock_pay_origin:app",
                "--host",
                "127.0.0.1",
                "--port",
                "18477",
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        gateway_env = {**os.environ, "VINFER_ORIGIN_TOKEN": ORIGIN_TOKEN}
        gateway = None
        try:
            wait_for(f"{ORIGIN}/v1/models", timeout=20)
            gateway = subprocess.Popen(
                [
                    "pay",
                    "--sandbox",
                    "server",
                    "start",
                    str(runtime),
                    "--bind",
                    "127.0.0.1:11402",
                ],
                cwd=ROOT,
                env=gateway_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            wait_for(f"{GATEWAY}/v1/models")
            payload = {
                "model": "bitnet-2b",
                "messages": [{"role": "user", "content": "test"}],
                "max_tokens": 1,
                "stream": False,
            }
            challenge = httpx.post(
                f"{GATEWAY}/v1/chat/completions", json=payload, timeout=10
            )
            assert challenge.status_code == 402, challenge.text
            assert "payment-required" in challenge.headers

            paid = subprocess.run(
                [
                    "pay",
                    "--sandbox",
                    "curl",
                    "-sS",
                    "-X",
                    "POST",
                    f"{GATEWAY}/v1/chat/completions",
                    "-H",
                    "content-type: application/json",
                    "--data",
                    json.dumps(payload, separators=(",", ":")),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=90,
            )
            body = json.loads(paid.stdout)
            assert body["usage"] == {
                "prompt_tokens": 4,
                "completion_tokens": 1,
                "total_tokens": 5,
            }
            assert body["x_vinfer"]["receipt"]["receipt_id"]
            print(
                "pay sandbox PASS: 402 challenge -> x402 payment -> authenticated origin"
            )
        finally:
            if gateway is not None:
                stop(gateway)
            stop(origin)


if __name__ == "__main__":
    main()
