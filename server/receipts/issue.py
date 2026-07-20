"""Issue and optionally relay one hash-only receipt."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from server.receipts.relay_client import post_receipt
from server.receipts.solana import attestation_pda


async def issue_receipt(
    *,
    signer,
    prompt: str | bytes,
    text: str,
    model_hash: bytes,
    metrics: dict,
    attestation: Callable[[], dict],
    receipts,
    log_name: str = "vinfer",
) -> dict:
    started = time.perf_counter()
    try:
        receipt = signer.sign_receipt(prompt, text, model_hash)
    finally:
        metrics["receipt_sign_ms"] = round(
            (time.perf_counter() - started) * 1000.0, 3
        )
    receipt.update(
        {
            "attestation": attestation(),
            "attestation_pda": attestation_pda(receipt["enclave_pubkey_b64"]),
            "onchain_status": "not-posted",
        }
    )
    timing_fields = (
        "receipt_post_ms",
        "receipt_confirm_ms",
        "solana_cu",
        "solana_fee_lamports",
    )
    for key in timing_fields:
        metrics[key] = 0
    try:
        posted = await post_receipt(receipt)
        if posted:
            for key in ("onchain_status", "receipt_index", "receipt_pda", "receipt_tx"):
                receipt[key] = posted[key]
            for key in timing_fields:
                metrics[key] = posted[key]
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(log_name).warning(
            "receipt relay failed for receipt_id=%s (%s)",
            receipt["receipt_id"],
            type(exc).__name__,
        )
    receipts[receipt["receipt_id"]] = receipt
    return receipt
