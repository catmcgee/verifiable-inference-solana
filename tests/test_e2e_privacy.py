from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import AsyncMock, patch

from server.crypto.hpke_box import EnclaveHpkeKey
from server.crypto.session_box import (
    ServerSession,
    client_open_response,
    client_open_session,
)
from fastapi import HTTPException

from server.main import SealedChatRequest, app, chat_e2e
from server.receipts.request_hash import canonical_request


class EndToEndPrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def test_sealed_chat_keeps_text_out_of_wire_response(self):
        enclave_key = EnclaveHpkeKey()
        prompt = "synthetic private browser prompt"
        response_text = "synthetic private model response"
        messages = [{"role": "user", "content": prompt}]
        plaintext = json.dumps(
            {"schema": "vinfer-e2e-chat-v1", "messages": messages}
        ).encode()
        wire, session_key = client_open_session(enclave_key.public_key_b64, plaintext)
        request = SealedChatRequest(model="bitnet-2b", max_tokens=17, **wire)
        result = {
            "text": response_text,
            "metrics": {"e2e_ms": 1.0},
            "usage": {
                "prompt_tokens": 4,
                "completion_tokens": 5,
                "total_tokens": 9,
            },
        }
        receipt = {"receipt_id": "receipt-test", "prompt_hash": "0" * 64}
        signer = AsyncMock(return_value=receipt)
        app.state.hpke = enclave_key
        app.state.receipts = {}

        with (
            patch("server.main.access.require", return_value=("browser-session", None)),
            patch("server.main._servable"),
            patch("server.main._chat", new=AsyncMock(return_value=result)),
            patch("server.main._sign", new=signer),
        ):
            http_response = await chat_e2e(request, object())

        body = json.loads(http_response.body)
        encoded_body = http_response.body.decode()
        self.assertNotIn(prompt, encoded_body)
        self.assertNotIn(response_text, encoded_body)
        self.assertEqual(
            client_open_response(
                session_key, body["resp_nonce"], body["sealed_response"]
            ).decode(),
            response_text,
        )
        metrics = json.loads(
            client_open_response(
                session_key,
                body["sealed_metrics"]["resp_nonce"],
                body["sealed_metrics"]["sealed_response"],
            )
        )
        usage = json.loads(
            client_open_response(
                session_key,
                body["sealed_usage"]["resp_nonce"],
                body["sealed_usage"]["sealed_response"],
            )
        )
        self.assertEqual(metrics["input_mode"], "e2e-sealed")
        self.assertEqual(usage["total_tokens"], 9)
        self.assertEqual(
            signer.await_args.args[0],
            canonical_request(
                endpoint="openai-chat-completions",
                model="bitnet-2b",
                messages=messages,
                max_tokens=17,
            ),
        )

    async def test_streamed_chat_seals_every_token_chunk(self):
        enclave_key = EnclaveHpkeKey()
        prompt = "synthetic private streaming prompt"
        response_text = "sealed stream"
        messages = [{"role": "user", "content": prompt}]
        wire, session_key = client_open_session(
            enclave_key.public_key_b64,
            json.dumps({"schema": "vinfer-e2e-chat-v1", "messages": messages}).encode(),
        )
        request = SealedChatRequest(
            model="bitnet-2b", max_tokens=8, stream=True, **wire
        )
        result = {
            "text": response_text,
            "metrics": {"e2e_ms": 1.0},
            "usage": {
                "prompt_tokens": 4,
                "completion_tokens": 2,
                "total_tokens": 6,
            },
        }

        class Runtime:
            async def chat_stream(self, _messages, _max_tokens):
                yield {"type": "token", "text": "sealed "}
                yield {"type": "token", "text": "stream"}
                yield {"type": "done", "result": result}

        app.state.hpke = enclave_key
        app.state.receipts = {}
        receipt = {"receipt_id": "receipt-stream", "prompt_hash": "0" * 64}
        with (
            patch("server.main.access.require", return_value=("browser-session", None)),
            patch("server.main._servable"),
            patch("server.main.runtimes.for_model", return_value=Runtime()),
            patch("server.main._sign", new=AsyncMock(return_value=receipt)),
        ):
            http_response = await chat_e2e(request, object())
            chunks = []
            async for chunk in http_response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

        wire_response = "".join(chunks)
        self.assertNotIn(prompt, wire_response)
        self.assertNotIn(response_text, wire_response)
        events = [
            json.loads(line[6:])
            for line in wire_response.splitlines()
            if line.startswith("data: ") and line != "data: [DONE]"
        ]
        deltas = [event["sealed_delta"] for event in events if "sealed_delta" in event]
        opened = "".join(
            client_open_response(
                session_key, delta["resp_nonce"], delta["sealed_response"]
            ).decode()
            for delta in deltas
        )
        self.assertEqual(opened, response_text)
        final = events[-1]
        self.assertEqual(
            client_open_response(
                session_key, final["resp_nonce"], final["sealed_response"]
            ).decode(),
            response_text,
        )

    async def test_sealed_chat_validates_inner_messages(self):
        enclave_key = EnclaveHpkeKey()
        wire, _ = client_open_session(
            enclave_key.public_key_b64,
            json.dumps(
                {
                    "schema": "vinfer-e2e-chat-v1",
                    "messages": [{"role": "tool", "content": "not allowed"}],
                }
            ).encode(),
        )
        app.state.hpke = enclave_key
        with (
            patch("server.main.access.require", return_value=("browser-session", None)),
            patch("server.main._servable"),
            self.assertRaises(HTTPException) as raised,
        ):
            await chat_e2e(SealedChatRequest(model="bitnet-2b", **wire), object())
        self.assertEqual(raised.exception.status_code, 400)

    @unittest.skipUnless(
        shutil.which("node") and Path("web/node_modules/@hpke/core").exists(),
        "frontend HPKE dependencies are not installed",
    )
    async def test_browser_hpke_is_compatible_with_enclave_session(self):
        enclave_key = EnclaveHpkeKey()
        prompt = "synthetic browser interoperability prompt"
        response_text = "synthetic sealed interoperability response"
        script = r"""
import { createSealedSession } from "./web/lib/e2e.ts";
const session = await createSealedSession(
  process.argv[1],
  new TextEncoder().encode(process.argv[2]),
);
process.stdout.write(JSON.stringify({enc: session.enc, ciphertext: session.ciphertext}) + "\n");
let input = "";
for await (const chunk of process.stdin) input += chunk;
const opened = await session.open(JSON.parse(input));
process.stdout.write(new TextDecoder().decode(opened) + "\n");
"""
        process = subprocess.Popen(
            [
                "node",
                "--experimental-strip-types",
                "--input-type=module",
                "-e",
                script,
                enclave_key.public_key_b64,
                prompt,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        wire_line = process.stdout.readline()
        wire = json.loads(wire_line)
        self.assertNotIn(prompt, wire_line)

        server_session = ServerSession(enclave_key, wire["enc"])
        self.assertEqual(
            server_session.open_prompt(wire["ciphertext"]).decode(), prompt
        )
        sealed_response = server_session.seal_response(response_text.encode())
        process.stdin.write(json.dumps(sealed_response))
        process.stdin.close()
        opened = process.stdout.readline().rstrip("\n")
        return_code = process.wait(timeout=15)
        stderr = process.stderr.read() if process.stderr else ""
        process.stdout.close()
        if process.stderr:
            process.stderr.close()
        self.assertEqual(return_code, 0, stderr)
        self.assertEqual(opened, response_text)


if __name__ == "__main__":
    unittest.main()
