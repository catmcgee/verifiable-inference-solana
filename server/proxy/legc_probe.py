"""Matched direct-versus-SNP-proxied streaming Claude latency probe."""

from __future__ import annotations

import concurrent.futures
import itertools
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import jsonschema


HERE = Path(__file__).resolve().parents[2] / "harness"
VALIDATOR = jsonschema.Draft202012Validator(
    json.loads((HERE / "schema.json").read_text())
)
DIRECT_API = "https://api.anthropic.com/v1/messages"


def parse_stream_event(event: dict, leg: str) -> tuple[bool, dict]:
    """Return whether an event contains text and any token usage it carries."""
    error = event.get("error")
    if error:
        raise RuntimeError(
            f"provider stream error: {error.get('type', 'unknown')}: "
            f"{error.get('message', 'no message')}"
        )
    if leg == "C-direct":
        if event.get("type") == "content_block_delta":
            return bool(event.get("delta", {}).get("text")), {}
        if event.get("type") == "message_start":
            return False, event.get("message", {}).get("usage", {})
        if event.get("type") == "message_delta":
            return False, event.get("usage", {})
        return False, {}

    choices = event.get("choices", [])
    text = choices[0].get("delta", {}).get("content") if choices else None
    return bool(text), event.get("usage", {})


def prompt_for_tokens(target: int) -> str:
    prefix = (
        "Explain how memory bandwidth limits autoregressive inference. "
        "Use concrete technical language and finish with one practical implication. Context: "
    )
    return prefix + "measurement " * max(1, target - 24)


def measure(
    api_key: str,
    model: str,
    prompt: str,
    requested_prompt_tokens: int,
    max_tokens: int,
    run_id: str,
    leg: str,
    concurrency: int,
    api: str,
    proxy_token: str = "",
) -> dict:
    headers = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
    if leg == "C-direct":
        headers["x-api-key"] = api_key
    else:
        headers["authorization"] = f"Bearer {proxy_token}"
    t0 = time.perf_counter()
    tok_times: list[float] = []
    usage: dict = {}
    with httpx.Client(timeout=180) as client:
        with client.stream(
            "POST",
            api,
            headers=headers,
            json={
                "model": model,
                "max_tokens": max_tokens,
                "stream": True,
                "messages": [{"role": "user", "content": prompt}],
            },
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    continue
                event = json.loads(payload)
                has_text, event_usage = parse_stream_event(event, leg)
                if has_text:
                    tok_times.append(time.perf_counter())
                usage.update(event_usage)
    if not tok_times:
        raise RuntimeError("no stream deltas")
    itls = [
        (tok_times[i] - tok_times[i - 1]) * 1000 for i in range(1, len(tok_times))
    ] or [0.0]
    ordered = sorted(itls)
    generated_seconds = tok_times[-1] - tok_times[0]
    output_token_count = int(
        usage.get("output_tokens", usage.get("completion_tokens", len(tok_times)))
    )
    record = {
        "run_id": run_id,
        "leg": leg,
        "model": model,
        "quant": "api",
        "sev_mode": "off" if leg == "C-direct" else "snp",
        "input_mode": "tls",
        "threads": 0,
        "numa_policy": "n/a",
        # Match the frozen harness convention: this field is the requested
        # matrix shape. Anthropic's actual tokenizer count is used by billing
        # but cannot be added without migrating the frozen v1 schema.
        "prompt_tokens": requested_prompt_tokens,
        "output_tokens": output_token_count,
        "batch": 1,
        "concurrency": concurrency,
        "ttft_ms": round((tok_times[0] - t0) * 1000, 3),
        "itl_ms_p50": round(statistics.median(ordered), 3),
        "itl_ms_p99": round(
            ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))], 3
        ),
        "tokens_per_s": round(max(0, output_token_count - 1) / generated_seconds, 3)
        if generated_seconds > 0
        else 0,
        "e2e_ms": round((tok_times[-1] - t0) * 1000, 3),
        "attest_fetch_ms": 0,
        "attest_verify_ms": 0,
        "receipt_sign_ms": 0,
        "receipt_post_ms": 0,
        "receipt_confirm_ms": 0,
        "solana_cu": 0,
        "solana_fee_lamports": 0,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    VALIDATOR.validate(record)
    return record


def run(out: Path) -> dict:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    proxy_token = os.environ["VINFER_PROXY_TOKEN"]
    proxy_api = os.environ.get(
        "VINFER_C_PROXY_API", "http://127.0.0.1:8480/v1/chat/completions"
    )
    model = os.environ.get("VINFER_C_MODEL", "claude-haiku-4-5-20251001")
    n = int(os.environ.get("VINFER_C_N", "8"))
    completed = (
        {json.loads(line)["run_id"] for line in out.read_text().splitlines()}
        if out.exists()
        else set()
    )
    jobs = []
    for prompt_tokens in (128, 1024):
        for output_tokens in (128, 512):
            for concurrency in (1, 8):
                for leg in ("C-direct", "C-proxied"):
                    for index in range(n):
                        run_id = f"{leg}-{prompt_tokens}-{output_tokens}-c{concurrency}-{index}"
                        if run_id not in completed:
                            jobs.append(
                                (
                                    leg,
                                    prompt_tokens,
                                    output_tokens,
                                    concurrency,
                                    index,
                                    run_id,
                                )
                            )

    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("a") as handle:
        for cell, group_iter in itertools.groupby(
            jobs, key=lambda job: (job[0], job[1], job[2], job[3])
        ):
            group = list(group_iter)
            concurrency = cell[3]
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [
                    pool.submit(
                        measure,
                        api_key,
                        model,
                        prompt_for_tokens(pt),
                        pt,
                        ot,
                        run_id,
                        leg,
                        concurrency,
                        DIRECT_API if leg == "C-direct" else proxy_api,
                        proxy_token,
                    )
                    for leg, pt, ot, concurrency, _index, run_id in group
                ]
                for future in concurrent.futures.as_completed(futures):
                    record = future.result()
                    handle.write(json.dumps(record, sort_keys=True) + "\n")
                    handle.flush()
                    written += 1
                    print(record["run_id"], record["ttft_ms"], record["e2e_ms"])
    return {"planned": len(jobs), "written": written, "out": str(out)}


if __name__ == "__main__":
    import sys

    print(
        json.dumps(
            run(Path(sys.argv[1] if len(sys.argv) > 1 else "runs/legC-full.jsonl")),
            indent=2,
        )
    )
