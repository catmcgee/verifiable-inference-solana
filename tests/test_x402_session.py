import struct
import tempfile
import unittest
from types import SimpleNamespace

from nacl.signing import SigningKey
from solders.pubkey import Pubkey

from server.x402.chain import DISCRIMINATOR, parse_channel
from server.x402.session import (
    Channel,
    ChannelStore,
    InsufficientFunds,
    Voucher,
    voucher_message,
)


def voucher(
    signer: SigningKey,
    channel: bytes,
    cumulative: int,
    expires: int = 0,
) -> Voucher:
    signature = signer.sign(voucher_message(channel, cumulative, expires)).signature
    return Voucher(
        channel_b58="Chan",
        channel_bytes=channel,
        cumulative_amount=cumulative,
        expires_at=expires,
        signer_pubkey=bytes(signer.verify_key),
        signature=signature,
    )


class X402SessionTests(unittest.TestCase):
    def test_voucher_meter_and_restart(self) -> None:
        signer = SigningKey.generate()
        channel_bytes = bytes(32)
        channel = Channel(
            channel_b58="Chan",
            authorized_signer=bytes(signer.verify_key),
            deposit=1_000,
        )

        channel.accept_voucher(voucher(signer, channel_bytes, 500))
        self.assertEqual(channel.available, 500)
        channel.debit(200)
        self.assertEqual((channel.spent, channel.available), (200, 300))

        with self.assertRaises(ValueError):
            channel.accept_voucher(voucher(signer, channel_bytes, 400))

        channel.accept_voucher(voucher(signer, channel_bytes, 800))
        self.assertEqual(channel.available, 600)

        with self.assertRaises(InsufficientFunds) as error:
            channel.debit(10_000)
        self.assertEqual(error.exception.available, 600)

        with self.assertRaises(ValueError):
            channel.accept_voucher(voucher(SigningKey.generate(), channel_bytes, 900))

        tampered = voucher(signer, channel_bytes, 900)
        tampered.signature = bytes(64)
        self.assertFalse(tampered.verify())

        with self.assertRaises(ValueError):
            channel.accept_voucher(voucher(signer, channel_bytes, 5_000))

        with tempfile.TemporaryDirectory() as directory:
            database = f"{directory}/channels.sqlite3"
            account = SimpleNamespace(
                address="11111111111111111111111111111111",
                opened_slot=10,
                authorized_signer=bytes(signer.verify_key),
                payer="payer",
                payee="payee",
                mint="mint",
                vault="vault",
                deposit=1_000,
                authorized_cumulative=0,
                settled=0,
                status="open",
            )
            store = ChannelStore(database)
            store.sync_onchain(account)
            stored_voucher = voucher(signer, channel_bytes, 500)
            stored_voucher.channel_b58 = account.address
            store.authorize_and_debit(stored_voucher, 200)

            restarted = ChannelStore(database)
            self.assertEqual(restarted.get(account.address).spent, 200)
            account.opened_slot = 11
            restarted.sync_onchain(account)
            self.assertEqual(restarted.get(account.address).spent, 0)

    def test_channel_account_layout_is_exact(self) -> None:
        signer = SigningKey.generate()
        keys = [bytes(Pubkey.new_unique()) for _ in range(4)]
        raw = b"".join(
            [
                DISCRIMINATOR,
                *keys,
                bytes(signer.verify_key),
                bytes([9]) * 32,
                struct.pack("<QQQQqIBB", 99, 1_000, 500, 200, 123, 900, 1, 7),
                bytes([8]),
            ]
        )
        address = "11111111111111111111111111111111"
        parsed = parse_channel(address, raw)

        self.assertEqual((parsed.opened_slot, parsed.deposit), (99, 1_000))
        self.assertEqual((parsed.authorized_cumulative, parsed.settled), (500, 200))
        self.assertEqual((parsed.status, parsed.grace_seconds), ("closing", 900))
        with self.assertRaises(ValueError):
            parse_channel(address, raw + b"\x00")


if __name__ == "__main__":
    unittest.main()
