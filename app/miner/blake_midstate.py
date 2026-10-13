"""
Blake-256 midstate for the GPU kernels.

The first 64 bytes of an 80-byte block header never change while nonces are searched, so the
first of Blake-256's two compressions is done once here on the host; the kernels only run the
second one (the one that contains the nonce). The result (the 8-word chaining value) is appended
to the 76-byte header prefix: the kernel's header buffer is 19 header words + 8 midstate words.
"""
import struct

HEADER_BUF_WORDS = 19 + 8
HEADER_BUF_BYTES = HEADER_BUF_WORDS * 4

_IV = (0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
       0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19)
_C = (0x243F6A88, 0x85A308D3, 0x13198A2E, 0x03707344, 0xA4093822, 0x299F31D0, 0x082EFA98, 0xEC4E6C89,
      0x452821E6, 0x38D01377, 0xBE5466CF, 0x34E90C6C, 0xC0AC29B7, 0xC97C50DD, 0x3F84D5B5, 0xB5470917)
_SIGMA = ((0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
          (14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3),
          (11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4),
          (7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8),
          (9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13),
          (2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9),
          (12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11),
          (13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10),
          (6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5),
          (10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0))
_G_STEPS = ((0, 4, 8, 12), (1, 5, 9, 13), (2, 6, 10, 14), (3, 7, 11, 15),
            (0, 5, 10, 15), (1, 6, 11, 12), (2, 7, 8, 13), (3, 4, 9, 14))
_M32 = 0xFFFFFFFF


def _rotr(x, n):
    return ((x >> n) | (x << (32 - n))) & _M32


def blake256_compress(h, m, t0, t1=0):
    """One Blake-256 compression (14 rounds). h: 8 words (modified in place), m: 16 message words."""
    v = list(h) + list(_C[:8])
    v[12] ^= t0
    v[13] ^= t0
    v[14] ^= t1
    v[15] ^= t1
    for r in range(14):
        s = _SIGMA[r % 10]
        for i, (a, b, c, d) in enumerate(_G_STEPS):
            v[a] = (v[a] + v[b] + (m[s[2 * i]] ^ _C[s[2 * i + 1]])) & _M32
            v[d] = _rotr(v[d] ^ v[a], 16)
            v[c] = (v[c] + v[d]) & _M32
            v[b] = _rotr(v[b] ^ v[c], 12)
            v[a] = (v[a] + v[b] + (m[s[2 * i + 1]] ^ _C[s[2 * i]])) & _M32
            v[d] = _rotr(v[d] ^ v[a], 8)
            v[c] = (v[c] + v[d]) & _M32
            v[b] = _rotr(v[b] ^ v[c], 7)
    for i in range(8):
        h[i] ^= v[i] ^ v[i + 8]


def blake256_midstate(header64: bytes) -> tuple:
    """Chaining value after absorbing the first 64 header bytes (8 words)."""
    if len(header64) < 64:
        raise ValueError("need at least 64 header bytes")
    h = list(_IV)
    m = struct.unpack(">16I", header64[:64])
    blake256_compress(h, m, 512)
    return tuple(h)


def kernel_header_buffer(header76: bytes) -> bytes:
    """The HEADER_BUF_BYTES bytes the search kernels expect: 76-byte prefix + Blake-256 midstate."""
    if len(header76) != 76:
        raise ValueError(f"header prefix must be 76 bytes, got {len(header76)}")
    return header76 + struct.pack("<8I", *blake256_midstate(header76))
