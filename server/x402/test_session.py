"""Session voucher/channel unit tests: uv run python -m server.x402.test_session"""

from __future__ import annotations

import base64

from nacl.signing import SigningKey

from server.x402.session import (
    Channel, InsufficientFunds, Voucher, voucher_message,
)


def _voucher(signer: SigningKey, channel: bytes, cumulative: int, expires: int = 0) -> Voucher:
    sig = signer.sign(voucher_message(channel, cumulative, expires)).signature
    return Voucher(channel_b58="Chan", channel_bytes=channel,
                   cumulative_amount=cumulative, expires_at=expires,
                   signer_pubkey=bytes(signer.verify_key), signature=sig)


def run() -> None:
    signer = SigningKey.generate()
    chan = bytes(32)
    ch = Channel(channel_b58="Chan", authorized_signer=bytes(signer.verify_key), deposit=1000)

    # happy path: accept voucher, debit, meter
    ch.accept_voucher(_voucher(signer, chan, 500))
    assert ch.available == 500
    ch.debit(200); assert ch.spent == 200 and ch.available == 300

    # monotonic: stale/replayed voucher rejected
    try:
        ch.accept_voucher(_voucher(signer, chan, 400)); assert False, "stale accepted"
    except ValueError:
        pass

    # top up: higher cumulative accepted
    ch.accept_voucher(_voucher(signer, chan, 800)); assert ch.available == 600

    # insufficient funds when debit > available
    try:
        ch.debit(10_000); assert False, "overspend allowed"
    except InsufficientFunds as e:
        assert e.available == 600

    # wrong signer rejected
    other = SigningKey.generate()
    try:
        ch.accept_voucher(_voucher(other, chan, 900)); assert False, "wrong signer accepted"
    except ValueError:
        pass

    # tampered signature rejected by verify()
    v = _voucher(signer, chan, 900)
    v.signature = bytes(64)
    assert not v.verify()

    # voucher exceeding deposit rejected
    try:
        ch.accept_voucher(_voucher(signer, chan, 5000)); assert False, "over-deposit accepted"
    except ValueError:
        pass

    print("session tests PASS (accept/debit/meter, monotonic, topup, insufficient, "
          "wrong-signer, tamper, over-deposit)")


if __name__ == "__main__":
    run()
