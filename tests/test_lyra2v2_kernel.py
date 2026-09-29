"""
Regression tests for the OpenCL Lyra2REv2 kernel (app/miner/kernels/lyra2v2.cl).

Run:  python -m unittest tests.test_lyra2v2_kernel -v      (needs an OpenCL GPU; skipped otherwise)

Expected values were produced by the reference C implementation (sph/Vertcoin `lyra2re2_hash`,
compiled with -fno-strict-aliasing) which was itself checked against Monacoin Core: on a regtest
chain, every nonce found by Monacoin Core's own miner passes it and all smaller nonces fail it.
The NODE_BLOCKS below are real headers mined by monacoind (regtest, heights >= 60 where the node
switches from scrypt to Lyra2REv2); they need no reference implementation to check.
"""
import os
import struct
import sys
import unittest
from ctypes import c_uint

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.miner.opencl_backend import OpenCLBackend, OpenCLContext

KERNEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "app", "miner", "kernels", "lyra2v2.cl")

# (80-byte header hex, Lyra2REv2 hash hex)
KNOWN_ANSWERS = [('000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f404142434445464748494a4b4c4d4e4f',
  '2246faafca15a01a35c81a3f801fe8338942565bdb75a505517372aa0c7afdd0'),
 ('4f4e4d4c4b4a494847464544434241403f3e3d3c3b3a393837363534333231302f2e2d2c2b2a292827262524232221201f1e1d1c1b1a191817161514131211100f0e0d0c0b0a09080706050403020100',
  'c1b23faa69426662e2115aaa8538eeff15920aa274d2eed25b873bc7f9c23d57'),
 ('af8ce647b0c9c1d50836f218c971f65aea9f32fcb55582d108760742abb066a693adcd87d3e3ec190eea30ec458d063c7ba196f049f6552c9f35dbf4ee2d38f9d0193d2ac8ba5b406c00c6d102e1c9ed',
  'fcca2002f1fed6c78fd872b38b6a8f02f3fa15e58a2ed09be77c046a8ec399a1')]

# Outputs of every stage for KNOWN_ANSWERS[0]:
# blake256, keccak256, cubehash256, lyra2(4x4), skein(512->256), cubehash256, bmw256
STAGES_HEADER0 = ['0e0825862e20f04262ceac23bd1ed7b954ec1a27eb8a25f9a9dd694f9db5b831',
 '8da57b5cd47fa368d2be58542172ce259e2eade74bb027292b8734e4bfe5e343',
 '38836d5475a3cff349082251579816492cb5a8f986957bfc9227f8eb5de11ed9',
 'd79f6e11b7e4702a2b53b54bf45b033fe09bd21ec36626f0242db393c9cd61c6',
 '06944e848abb584bfea95bfa9eae9d0e070e3d8e754e871df0a97668f9e1c097',
 'f8e8c07ccccb2e3710eacc46810b1f8a9ab2f35357ed1df2357b8043b5a3c93f',
 '2246faafca15a01a35c81a3f801fe8338942565bdb75a505517372aa0c7afdd0']

# (height, 80-byte header hex) of blocks mined by Monacoin Core's regtest miner, which tries
# nonces 0, 1, 2 ... and stops at the first one below the target 0x7fffff00...00
NODE_BLOCKS = [(60,
  '000000204382c56c2ee11cdf87ff7691ba5aa61e9bae1268f227cc4a2e8740d5b8ef7c4ff878d8a5ea03e2c0d6959e82e33c24063857dbbc6a759298bae56b08a223f1235286ba6affff7f2000000000'),
 (61,
  '000000202f53b46516e45ac93fcef7441b82b7472c38fd8a4c9310a10e84744b9db10c28118d0a2cc7d8338edf1859f40c878807762316541222d369ed4e820d3b9e4fbe5286ba6affff7f2001000000'),
 (62,
  '00000020710c10dfcde0bc9fead84da36a10b1c35c0e537f23e9603d0f8975066e7d15c786bea083bf9c11f3bf686b8b9e6e4e88acb9a2ab7f89b76ebd67a885937e91e65386ba6affff7f2000000000'),
 (63,
  '000000208ce5ceba20b1fb52ff7b926b4469600cc8ee434965eba62d1a883630339b26fc38ca4c731b3dc3e0455f4312c7dfd6ab3d1376042be400ae424f7d6d334fc20b5386ba6affff7f2000000000'),
 (64,
  '00000020eccc14eee04b6f3a93b75d8ad375cf5870eaf2defff1093f9ec8fe7ad727efb0a9a7ea86a006846aed192ad311f7e157f6271b439e2ee564e9db4fbee6f86e2d5386ba6affff7f2002000000'),
 (65,
  '00000020b6afa4b9af6362a7803220f5d6f739c63834ea8fb2c5c78a067f878b88954a367cb1755d8e05b98f1f85209a5f0d0cea317a37eef704fdd0dabfa3e4588a3a7d5386ba6affff7f2001000000'),
 (66,
  '00000020e8b30f99e83dcdcc0ed267dd50e85e8fa9a807743b19c055b35cef1772e315bb70b0af50449d35d79f18d95b2d46e50a5575f72b6641da5b24eadf6eaa3cacd85386ba6affff7f2003000000'),
 (67,
  '00000020aca58678d9c8a6ff12765992801b4deed129ddfa93c57615214727372d6f9b27d88e4ae35b84967b6a3494729cde9833f7ee584b873691236806c5262e6962435386ba6affff7f2002000000'),
 (68,
  '000000207e33a1436d3ab9ed561ea3d0aaba8b3d8ce1dbcd56c44ccea9284a3fc85ec5aa99087d1e957d5c9d55afd8e912009af8ecd0cea165add9f8640e280fbb331fc05486ba6affff7f2003000000'),
 (69,
  '000000209ffa978071516342ac8345ce6777e23ab8c449da5f351da76bf96b6da0dc75eee906f1944fc77fef12108e07372e786a41000978e7acd181d2fd05db50d5cf035486ba6affff7f2000000000'),
 (70,
  '0000002048b9dd04ad3007cf046365596f17f72fe1fc7b6f55b574e8fe6d538ea786abcc5d832713202cbf1bbd8f1b9007490da35523281c57c33268414bac48881b84505486ba6affff7f2000000000'),
 (71,
  '0000002021d122a4ce79c5fe2709a611157a29155f7b74b3252c5e3f61b872a2538e129eded39b34bad74a43f387cb24333b6b7af6a767f659ed438a0c5c07b4eba247565486ba6affff7f2000000000'),
 (72,
  '0000002096e15cad02f4ff940d049e66aeffb14cee3bc5416cf1a2e79b2d24bf8bc8cd777650812269fbef4d9a5c4aac783bdf66e5ef265066cc1acbd193fee10c9a79e65486ba6affff7f2001000000'),
 (73,
  '000000202e216c1a1fdff940cb9739c37863f14b0d02546bcb8a4e3530e6bcb7015c0fa4811fbca57a200787bef34d39a4bdc0da01e9b85ef5246bf7ac1ccfabf230471e5486ba6affff7f2003000000'),
 (74,
  '0000002008861edc0f334dded29162d94718af458ee9ff4700483b5fdea1ad25042ac719d21489d92ea7ce5a862874ca73302a4eb9869d8b806985f8f97a8036ffd36aff5586ba6affff7f2000000000'),
 (75,
  '000000208f3581f1d68882825206bc9a1bd6d7c81681777f811ddb22adefad9be2a5e71413bfa3be5c8df1df1fbf4fc4a79860cefda9c73cfd045c2b4b541193a98c5aa65586ba6affff7f2000000000')]

REGTEST_TARGET_HI = 0x7FFFFF00
REGTEST_TARGET_LO = 0x00000000


def _open_context(options=""):
    try:
        platforms = OpenCLBackend.get_platforms()
        if not platforms:
            return None
        for p in platforms:
            devs = OpenCLBackend.get_devices(p["id"])
            if devs:
                ctx = OpenCLContext(p["id"], devs[0]["id"])
                with open(KERNEL_PATH, encoding="utf-8") as f:
                    ctx.build_program(f.read(), options=options)
                return ctx
    except Exception:
        return None
    return None


class KernelTestBase(unittest.TestCase):
    ctx = None

    @classmethod
    def setUpClass(cls):
        cls.ctx = _open_context(cls.build_options)
        if cls.ctx is None:
            raise unittest.SkipTest("no usable OpenCL GPU")

    @classmethod
    def tearDownClass(cls):
        if cls.ctx:
            cls.ctx.release()

    build_options = ""


class TestStages(KernelTestBase):
    build_options = "-DDEBUG_STAGES"

    def _run_stages(self, header):
        ctx = self.ctx
        k = ctx.get_kernel("debug_stages")
        bh = ctx.create_buffer(80)
        bo = ctx.create_buffer(7 * 32)
        ctx.write_buffer(bh, (c_uint * 20).from_buffer_copy(header), 80)
        ctx.set_arg_mem(k, 0, bh)
        ctx.set_arg_mem(k, 1, bo)
        ctx.run_kernel_1d(k, 1, 1)
        ctx.finish()
        out = (c_uint * 56)()
        ctx.read_buffer(bo, out, 224)
        return [b"".join(struct.pack("<I", out[i * 8 + j]) for j in range(8)).hex() for i in range(7)]

    def test_every_stage_matches_reference(self):
        header = bytes.fromhex(KNOWN_ANSWERS[0][0])
        got = self._run_stages(header)
        names = ["blake256", "keccak256", "cubehash256", "lyra2", "skein", "cubehash256 (2nd)", "bmw256"]
        for name, g, e in zip(names, got, STAGES_HEADER0):
            self.assertEqual(g, e, f"stage {name} differs from the reference")

    def test_full_hash_known_answers(self):
        for header_hex, hash_hex in KNOWN_ANSWERS:
            got = self._run_stages(bytes.fromhex(header_hex))[6]
            self.assertEqual(got, hash_hex)


class TestSearchKernel(KernelTestBase):
    build_options = "-cl-mad-enable -cl-no-signed-zeros -cl-fast-relaxed-math"
    kernel_name = "search_lyra2v2"
    size_multiple = 1

    def _search(self, header76, base, count, target_hi, target_lo):
        ctx = self.ctx
        count = -(-count // self.size_multiple) * self.size_multiple
        k = ctx.get_kernel(self.kernel_name)
        bh = ctx.create_buffer(76)
        bn = ctx.create_buffer(64)
        bc = ctx.create_buffer(4)
        ctx.write_buffer(bh, (c_uint * 19).from_buffer_copy(header76), 76)
        ctx.write_buffer(bc, (c_uint * 1)(0), 4)
        ctx.set_arg_mem(k, 0, bh)
        ctx.set_arg_uint(k, 1, base)
        ctx.set_arg_uint(k, 2, target_hi)
        ctx.set_arg_uint(k, 3, target_lo)
        ctx.set_arg_mem(k, 4, bn)
        ctx.set_arg_mem(k, 5, bc)
        ctx.run_kernel_1d(k, count, min(count, 128))
        ctx.finish()
        c = (c_uint * 1)(0)
        ctx.read_buffer(bc, c, 4)
        n = (c_uint * 16)()
        ctx.read_buffer(bn, n, 64)
        return c[0], sorted(n[i] for i in range(min(c[0], 16)))

    def test_hash_equal_to_target_is_a_winner(self):
        """The comparison is inclusive: a target equal to the hash's top 64 bits accepts that nonce."""
        header_hex, hash_hex = KNOWN_ANSWERS[1]
        header = bytes.fromhex(header_hex)
        h = bytes.fromhex(hash_hex)
        hi = struct.unpack("<I", h[28:32])[0]   # most significant 32-bit word of the 256-bit hash
        lo = struct.unpack("<I", h[24:28])[0]
        nonce = struct.unpack("<I", header[76:])[0]
        _, found = self._search(header[:76], nonce - 3, 8, hi, lo)
        self.assertIn(nonce, found)

    def test_tighter_target_excludes_it(self):
        header_hex, hash_hex = KNOWN_ANSWERS[1]
        header = bytes.fromhex(header_hex)
        h = bytes.fromhex(hash_hex)
        hi = struct.unpack("<I", h[28:32])[0]
        lo = struct.unpack("<I", h[24:28])[0]
        nonce = struct.unpack("<I", header[76:])[0]
        if lo > 0:
            _, found = self._search(header[:76], nonce, 1, hi, lo - 1)
        else:
            _, found = self._search(header[:76], nonce, 1, hi - 1, 0xFFFFFFFF)
        self.assertNotIn(nonce, found)

    def test_matches_monacoin_core_regtest_miner(self):
        """For real node-mined headers the first winning nonce must be exactly the node's nonce."""
        self.assertGreaterEqual(len(NODE_BLOCKS), 8)
        for height, header_hex in NODE_BLOCKS:
            header = bytes.fromhex(header_hex)
            node_nonce = struct.unpack("<I", header[76:])[0]
            _, found = self._search(header[:76], 0, 16, REGTEST_TARGET_HI, REGTEST_TARGET_LO)
            self.assertTrue(found, f"height {height}: kernel found no winner in nonces 0..15")
            self.assertEqual(found[0], node_nonce, f"height {height}: first winning nonce differs from the node's")

    def test_large_launch_win_rate(self):
        """A 65536-thread launch: impossible target -> nothing; regtest target -> about half win."""
        header = bytes.fromhex(NODE_BLOCKS[0][1])[:76]
        count, _ = self._search(header, 0, 1 << 16, 0, 0)
        self.assertEqual(count, 0)
        count, _ = self._search(header, 0, 1 << 16, REGTEST_TARGET_HI, REGTEST_TARGET_LO)
        self.assertGreater(count, 30000)   # 32768 expected, sigma = 128
        self.assertLess(count, 36000)


class TestSearchKernelNvidia(TestSearchKernel):
    """The 4-lane warp-shuffle kernel (NVIDIA only; skipped when it cannot be built)."""
    build_options = TestSearchKernel.build_options + " -DLYRA2_NV_SHFL"
    kernel_name = "search_lyra2v2_nv"
    size_multiple = 32


if __name__ == "__main__":
    unittest.main()
