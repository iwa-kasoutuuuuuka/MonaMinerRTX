"""
Tests for the pure-Python protocol code (no GPU needed):
    python -m unittest tests.test_solo_and_stratum -v
"""
import hashlib
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.miner.rpc_solo_client import SoloBlockTemplate, encode_script_num_push
from app.miner.stratum_client import (
    LYRA2REV2_DIFF_MULTIPLIER, StratumJob, diff_to_target, target_words,
)


def sha256d(b):
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


def decode_script_num_push(script):
    """Reference decoder for `CScript() << n`; returns (n, bytes consumed) and checks minimality."""
    op = script[0]
    if op == 0x00:
        return 0, 1
    if 0x51 <= op <= 0x60:
        return op - 0x50, 1
    data = script[1:1 + op]
    assert len(data) == op and 1 <= op <= 4
    assert not (data[-1] & 0x80), "sign bit set: would be a negative number"
    if op > 1:
        assert not (data[-1] == 0 and not (data[-2] & 0x80)), "non-minimal encoding"
    return int.from_bytes(data, "little"), 1 + op


class TestBip34Height(unittest.TestCase):
    def test_round_trip(self):
        heights = [1, 2, 16, 17, 60, 127, 128, 255, 256, 32767, 32768, 65535, 65536,
                   4_100_000, 4_194_303, 8_388_607]
        for h in heights:
            n, used = decode_script_num_push(encode_script_num_push(h))
            self.assertEqual(n, h)

    def test_known_encodings(self):
        self.assertEqual(encode_script_num_push(1), b"\x51")            # OP_1: the old code produced 01 01
        self.assertEqual(encode_script_num_push(16), b"\x60")
        self.assertEqual(encode_script_num_push(17), b"\x01\x11")
        self.assertEqual(encode_script_num_push(128), b"\x02\x80\x00")  # needs a pad byte
        self.assertEqual(encode_script_num_push(256), b"\x02\x00\x01")
        self.assertEqual(encode_script_num_push(32768), b"\x03\x00\x80\x00")
        # mainnet heights (~4.1M) need 3 bytes; the old code always emitted 2
        self.assertEqual(encode_script_num_push(4_100_000), b"\x03\xa0\x8f\x3e")


def make_gbt(height=4_100_000, witness=True, txs=()):
    gbt = {
        "height": height,
        "version": 0x20000000,
        "previousblockhash": "11" * 32,
        "bits": "1d00ffff",
        "curtime": 1_700_000_000,
        "coinbasevalue": 312_500_000,
        "target": "00000000ffff0000000000000000000000000000000000000000000000000000",
        "transactions": list(txs),
    }
    if witness:
        gbt["default_witness_commitment"] = "6a24aa21a9ed" + "22" * 32
    return gbt


SPK = bytes.fromhex("0014" + "33" * 20)


class TestSoloBlockTemplate(unittest.TestCase):
    def test_coinbase_starts_with_bip34_height(self):
        for height in (2, 60, 300, 4_100_000):
            tpl = SoloBlockTemplate(make_gbt(height), SPK, "addr")
            # version(4) | vin count(1) | prevout(36) | scriptSig len(1) | scriptSig
            script = tpl.cb_tx_bytes[4 + 1 + 36 + 1:]
            n, _ = decode_script_num_push(script)
            self.assertEqual(n, height)

    def test_txid_is_hash_of_non_witness_serialization(self):
        tpl = SoloBlockTemplate(make_gbt(), SPK, "addr")
        self.assertEqual(tpl.cb_hash, sha256d(tpl.cb_tx_bytes))
        self.assertEqual(tpl.merkle_root, tpl.cb_hash)  # single-transaction block

    def test_block_carries_coinbase_witness_when_commitment_present(self):
        tpl = SoloBlockTemplate(make_gbt(witness=True), SPK, "addr")
        block = tpl.assemble_full_block(0x12345678)
        self.assertEqual(block[76:80], struct.pack("<I", 0x12345678))
        self.assertEqual(block[80], 1)                        # one transaction
        self.assertEqual(block[81:85], struct.pack("<i", 1))  # tx version
        self.assertEqual(block[85:87], b"\x00\x01")           # segwit marker + flag
        # the witness (1 stack item of 32 zero bytes) sits right before the locktime
        self.assertEqual(block[-4:], b"\x00\x00\x00\x00")
        self.assertEqual(block[-4 - 34:-4], b"\x01\x20" + b"\x00" * 32)

    def test_block_without_commitment_has_plain_coinbase(self):
        tpl = SoloBlockTemplate(make_gbt(witness=False), SPK, "addr")
        block = tpl.assemble_full_block(0)
        self.assertEqual(block[80:], b"\x01" + tpl.cb_tx_bytes)

    def test_header_prefix_layout(self):
        tpl = SoloBlockTemplate(make_gbt(), SPK, "addr")
        h = tpl.header_76
        self.assertEqual(len(h), 76)
        self.assertEqual(h[:4], struct.pack("<i", 0x20000000))
        self.assertEqual(h[4:36], bytes.fromhex("11" * 32)[::-1])
        self.assertEqual(h[68:72], struct.pack("<I", 1_700_000_000))
        self.assertEqual(h[72:76], bytes.fromhex("1d00ffff")[::-1])

    def test_merkle_root_with_transactions(self):
        txs = [{"txid": "aa" * 32, "data": "00"}, {"txid": "bb" * 32, "data": "01"}]
        tpl = SoloBlockTemplate(make_gbt(txs=txs), SPK, "addr")
        leaves = [tpl.cb_hash, bytes.fromhex("aa" * 32)[::-1], bytes.fromhex("bb" * 32)[::-1]]
        leaves.append(leaves[-1])  # odd level: last hash is duplicated
        expected = sha256d(sha256d(leaves[0] + leaves[1]) + sha256d(leaves[2] + leaves[3]))
        self.assertEqual(tpl.merkle_root, expected)

    def test_target_words_are_not_replaced_by_a_fallback(self):
        # the old code turned a zero high word into 0x0000ffff, i.e. a wrong target
        tpl = SoloBlockTemplate(make_gbt(), SPK, "addr")
        self.assertEqual(tpl.target_high, 0x00000000)
        self.assertEqual(tpl.target_low, 0xFFFF0000)
        regtest = make_gbt()
        regtest["target"] = "7fffff" + "00" * 29
        tpl = SoloBlockTemplate(regtest, SPK, "addr")
        self.assertEqual((tpl.target_high, tpl.target_low), (0x7FFFFF00, 0))


class TestStratum(unittest.TestCase):
    def test_difficulty_to_target(self):
        diff1 = 0xFFFF << 208
        self.assertEqual(LYRA2REV2_DIFF_MULTIPLIER, 256.0)
        self.assertEqual(diff_to_target(1.0), diff1 * 256)
        self.assertEqual(diff_to_target(1.0, multiplier=1.0), diff1)
        self.assertEqual(diff_to_target(256.0), diff1)
        self.assertGreater(diff_to_target(0.5), diff_to_target(1.0))  # lower difficulty = easier target

    def test_target_words(self):
        self.assertEqual(target_words(0x7FFFFF << 232), (0x7FFFFF00, 0))
        self.assertEqual(target_words(0xFFFF << 208), (0, 0xFFFF0000))
        self.assertEqual(target_words((1 << 256) - 1), (0xFFFFFFFF, 0xFFFFFFFF))

    def test_header_prefix(self):
        job = StratumJob(
            job_id="j1", prevhash="".join(f"{i:02x}" * 4 for i in range(8)),
            coinb1="0100", coinb2="ff", merkle_branches=[], version="20000000",
            nbits="1d00ffff", ntime="65000000", clean_jobs=True)
        h = job.build_header_prefix("aabb", "0001")
        self.assertEqual(len(h), 76)
        coinbase = bytes.fromhex("0100" + "aabb" + "0001" + "ff")
        self.assertEqual(h[36:68], sha256d(coinbase))            # no branches: merkle root == coinbase hash
        self.assertEqual(h[:4], bytes.fromhex("20000000")[::-1])
        self.assertEqual(h[68:72], bytes.fromhex("65000000")[::-1])
        self.assertEqual(h[72:76], bytes.fromhex("1d00ffff")[::-1])
        # stratum sends prevhash as 8 words that are each byte-swapped in the header
        self.assertEqual(h[4:8], bytes.fromhex("00000000")[::-1])
        self.assertEqual(h[8:12], bytes.fromhex("01010101")[::-1])

    def test_multiplier_falls_back_after_repeated_low_difficulty_rejects(self):
        from app.miner.stratum_client import StratumClient
        client = StratumClient("h", 1, "u")
        client.difficulty = 2.0
        client.target = diff_to_target(2.0, client.diff_multiplier)
        low = [23, "Low difficulty share", None]
        client._note_share_result(False, low)
        client._note_share_result(True, None)      # an accepted share resets the counter
        client._note_share_result(False, low)
        client._note_share_result(False, low)
        self.assertEqual(client.diff_multiplier, LYRA2REV2_DIFF_MULTIPLIER)
        client._note_share_result(False, [21, "Job not found", None])  # other errors are ignored
        client._note_share_result(False, low)
        self.assertEqual(client.diff_multiplier, 1.0)
        self.assertEqual(client.target, diff_to_target(2.0, 1.0))


if __name__ == "__main__":
    unittest.main()
