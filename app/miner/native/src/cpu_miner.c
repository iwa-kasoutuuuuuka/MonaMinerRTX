/*
 * Native CPU scanner for MonaMiner: Lyra2REv2 nonce search over a range.
 * Built on the sph hash library and the Lyra2 reference code (see NOTICE.txt).
 * Called from Python through ctypes (which releases the GIL), one call per CPU thread.
 */
#include <stdint.h>
#include <string.h>
#include "sph_blake.h"
#include "sph_bmw.h"
#include "sph_cubehash.h"
#include "sph_keccak.h"
#include "sph_skein.h"
#include "Lyra2.h"

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif

static void lyra2re2_80(const uint8_t *in, uint32_t out[8]) {
    sph_blake256_context cb;
    sph_cubehash256_context cc;
    sph_keccak256_context ck;
    sph_skein256_context cs;
    sph_bmw256_context cm;
    uint32_t a[8], b[8];

    sph_blake256_init(&cb);   sph_blake256(&cb, in, 80);   sph_blake256_close(&cb, a);
    sph_keccak256_init(&ck);  sph_keccak256(&ck, a, 32);   sph_keccak256_close(&ck, b);
    sph_cubehash256_init(&cc); sph_cubehash256(&cc, b, 32); sph_cubehash256_close(&cc, a);
    LYRA2(b, 32, a, 32, a, 32, 1, 4, 4);
    sph_skein256_init(&cs);   sph_skein256(&cs, b, 32);    sph_skein256_close(&cs, a);
    sph_cubehash256_init(&cc); sph_cubehash256(&cc, a, 32); sph_cubehash256_close(&cc, b);
    sph_bmw256_init(&cm);     sph_bmw256(&cm, b, 32);      sph_bmw256_close(&cm, out);
}

/* Hash of an 80-byte header (32 bytes, as uint256 in memory order). */
EXPORT void cpu_hash(const uint8_t *header80, uint8_t *out32) {
    uint32_t h[8];
    lyra2re2_80(header80, h);
    memcpy(out32, h, 32);
}

/*
 * Tests `count` nonces starting at `start` (wrapping at 2^32). A nonce wins when the two most
 * significant 32-bit words of its hash are <= (target_hi, target_lo), the same rule as the GPU kernel.
 * Returns the number of winners; at most `max_found` of them are written to `found`.
 */
EXPORT uint32_t cpu_scan(const uint8_t *header76, uint32_t start, uint32_t count,
                         uint32_t target_hi, uint32_t target_lo,
                         uint32_t *found, uint32_t max_found) {
    uint8_t hdr[80];
    uint32_t h[8], n = 0, i;
    memcpy(hdr, header76, 76);
    for (i = 0; i < count; i++) {
        uint32_t nonce = start + i;
        hdr[76] = (uint8_t)nonce;
        hdr[77] = (uint8_t)(nonce >> 8);
        hdr[78] = (uint8_t)(nonce >> 16);
        hdr[79] = (uint8_t)(nonce >> 24);
        lyra2re2_80(hdr, h);
        if (h[7] < target_hi || (h[7] == target_hi && h[6] <= target_lo)) {
            if (n < max_found) found[n] = nonce;
            n++;
        }
    }
    return n;
}
