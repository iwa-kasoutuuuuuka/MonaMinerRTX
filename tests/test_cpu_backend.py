"""
Tests for the native CPU scanner (app/miner/native/lyra2re2_cpu.dll):
    python -m unittest tests.test_cpu_backend -v
Uses the same known answers as the GPU kernel tests (incl. real Monacoin Core regtest headers).
"""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.miner.cpu_backend import CpuBackend
from tests.test_lyra2v2_kernel import KNOWN_ANSWERS, NODE_BLOCKS, REGTEST_TARGET_HI, REGTEST_TARGET_LO


@unittest.skipUnless(CpuBackend.is_available(), "lyra2re2_cpu.dll not available")
class TestCpuBackend(unittest.TestCase):
    def test_known_answers(self):
        for header_hex, hash_hex in KNOWN_ANSWERS:
            self.assertEqual(CpuBackend.hash80(bytes.fromhex(header_hex)).hex(), hash_hex)

    def test_first_winner_matches_monacoin_core(self):
        for height, header_hex in NODE_BLOCKS:
            header = bytes.fromhex(header_hex)
            node_nonce = struct.unpack("<I", header[76:])[0]
            n, found = CpuBackend.scan(header[:76], 0, 16, REGTEST_TARGET_HI, REGTEST_TARGET_LO)
            self.assertGreater(n, 0)
            self.assertEqual(min(found), node_nonce, f"height {height}")

    def test_inclusive_target_and_wraparound(self):
        header_hex, hash_hex = KNOWN_ANSWERS[1]
        header = bytes.fromhex(header_hex)
        h = bytes.fromhex(hash_hex)
        hi = struct.unpack("<I", h[28:32])[0]
        lo = struct.unpack("<I", h[24:28])[0]
        nonce = struct.unpack("<I", header[76:])[0]
        self.assertIn(nonce, CpuBackend.scan(header[:76], nonce - 2, 5, hi, lo)[1])
        n, _ = CpuBackend.scan(header[:76], nonce, 1, hi, lo - 1 if lo else 0)
        self.assertEqual(n, 0)
        # a range that wraps past 2^32 must not crash and counts the right number of nonces
        n, found = CpuBackend.scan(header[:76], 0xFFFFFFFE, 4, 0xFFFFFFFF, 0xFFFFFFFF)
        self.assertEqual(n, 4)
        self.assertEqual(sorted(found), [0, 1, 0xFFFFFFFE, 0xFFFFFFFF])


if __name__ == "__main__":
    unittest.main()
