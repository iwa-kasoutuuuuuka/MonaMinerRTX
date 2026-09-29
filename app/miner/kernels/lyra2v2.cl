/*
 * OpenCL Lyra2REv2 kernel for MonaMiner (Monacoin PoW).
 *
 * Pipeline (identical to Monacoin Core's lyra2re2_hash):
 *   Blake256(80B) -> Keccak256 -> CubeHash256 -> Lyra2(nRows=4, nCols=4)
 *   -> Skein(512 state, 256-bit output) -> CubeHash256 -> BMW256
 *
 * Every stage is verified against the reference C implementation
 * (see tests/test_lyra2v2_kernel.py).
 *
 * Byte-string convention: an intermediate 256-bit hash is held as 8 x uint,
 * each uint being the little-endian decoding of 4 consecutive bytes (the same
 * memory layout as uint32_t hash[8] on a little-endian CPU).
 */

typedef uint  u32;
typedef ulong u64;

#define ROTL32(x, n) rotate((u32)(x), (u32)(n))
#define ROTR32(x, n) rotate((u32)(x), (u32)(32 - (n)))
#define ROTL64(x, n) rotate((u64)(x), (u64)(n))
#define ROTR64(x, n) rotate((u64)(x), (u64)(64 - (n)))
#define BSWAP32(x) ((((x) >> 24) & 0x000000FFu) | (((x) >> 8) & 0x0000FF00u) | \
                    (((x) << 8) & 0x00FF0000u) | (((x) << 24) & 0xFF000000u))

/* ------------------------------------------------------------------ */
/* Blake-256 (14 rounds), 80-byte message = 2 compression calls        */
/* ------------------------------------------------------------------ */
__constant u32 BLAKE_IV[8] = {
    0x6A09E667u, 0xBB67AE85u, 0x3C6EF372u, 0xA54FF53Au,
    0x510E527Fu, 0x9B05688Cu, 0x1F83D9ABu, 0x5BE0CD19u
};

__constant uchar BLAKE_SIGMA[10][16] = {
    {  0,  1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11, 12, 13, 14, 15 },
    { 14, 10,  4,  8,  9, 15, 13,  6,  1, 12,  0,  2, 11,  7,  5,  3 },
    { 11,  8, 12,  0,  5,  2, 15, 13, 10, 14,  3,  6,  7,  1,  9,  4 },
    {  7,  9,  3,  1, 13, 12, 11, 14,  2,  6,  5, 10,  4,  0, 15,  8 },
    {  9,  0,  5,  7,  2,  4, 10, 15, 14,  1, 11, 12,  6,  8,  3, 13 },
    {  2, 12,  6, 10,  0, 11,  8,  3,  4, 13,  7,  5, 15, 14,  1,  9 },
    { 12,  5,  1, 15, 14, 13,  4, 10,  0,  7,  6,  3,  9,  2,  8, 11 },
    { 13, 11,  7, 14, 12,  1,  3,  9,  5,  0, 15,  4,  8,  6,  2, 10 },
    {  6, 15, 14,  9, 11,  3,  0,  8, 12,  2, 13,  7,  1,  4, 10,  5 },
    { 10,  2,  8,  4,  7,  6,  1,  5, 15, 11,  9, 14,  3, 12, 13,  0 }
};

__constant u32 BLAKE_C[16] = {
    0x243F6A88u, 0x85A308D3u, 0x13198A2Eu, 0x03707344u,
    0xA4093822u, 0x299F31D0u, 0x082EFA98u, 0xEC4E6C89u,
    0x452821E6u, 0x38D01377u, 0xBE5466CFu, 0x34E90C6Cu,
    0xC0AC29B7u, 0xC97C50DDu, 0x3F84D5B5u, 0xB5470917u
};

#define BLAKE_G(a, b, c, d, i) do { \
    v[a] += v[b] + (m[s[2 * (i)]] ^ BLAKE_C[s[2 * (i) + 1]]); \
    v[d] = ROTR32(v[d] ^ v[a], 16); \
    v[c] += v[d]; \
    v[b] = ROTR32(v[b] ^ v[c], 12); \
    v[a] += v[b] + (m[s[2 * (i) + 1]] ^ BLAKE_C[s[2 * (i)]]); \
    v[d] = ROTR32(v[d] ^ v[a], 8); \
    v[c] += v[d]; \
    v[b] = ROTR32(v[b] ^ v[c], 7); \
} while (0)

static void blake256_compress(u32 h[8], const u32 m[16], u32 t0, u32 t1) {
    u32 v[16];
    #pragma unroll
    for (int i = 0; i < 8; i++) v[i] = h[i];
    v[8]  = BLAKE_C[0];
    v[9]  = BLAKE_C[1];
    v[10] = BLAKE_C[2];
    v[11] = BLAKE_C[3];
    v[12] = BLAKE_C[4] ^ t0;
    v[13] = BLAKE_C[5] ^ t0;
    v[14] = BLAKE_C[6] ^ t1;
    v[15] = BLAKE_C[7] ^ t1;

    #pragma unroll
    for (int r = 0; r < 14; r++) {
        __constant uchar *s = BLAKE_SIGMA[r % 10];
        BLAKE_G(0, 4,  8, 12, 0);
        BLAKE_G(1, 5,  9, 13, 1);
        BLAKE_G(2, 6, 10, 14, 2);
        BLAKE_G(3, 7, 11, 15, 3);
        BLAKE_G(0, 5, 10, 15, 4);
        BLAKE_G(1, 6, 11, 12, 5);
        BLAKE_G(2, 7,  8, 13, 6);
        BLAKE_G(3, 4,  9, 14, 7);
    }
    #pragma unroll
    for (int i = 0; i < 8; i++) h[i] ^= v[i] ^ v[i + 8];
}

/* header: 20 words (little-endian decoding of the 80 header bytes) -> out: hash bytes as LE words */
static void blake256_80(const u32 header[20], u32 out[8]) {
    u32 h[8], m[16];
    #pragma unroll
    for (int i = 0; i < 8; i++) h[i] = BLAKE_IV[i];

    #pragma unroll
    for (int i = 0; i < 16; i++) m[i] = BSWAP32(header[i]);
    blake256_compress(h, m, 512u, 0u);

    #pragma unroll
    for (int i = 0; i < 4; i++) m[i] = BSWAP32(header[16 + i]);
    m[4] = 0x80000000u;
    #pragma unroll
    for (int i = 5; i < 13; i++) m[i] = 0u;
    m[13] = 1u;
    m[14] = 0u;
    m[15] = 640u;
    blake256_compress(h, m, 640u, 0u);

    #pragma unroll
    for (int i = 0; i < 8; i++) out[i] = BSWAP32(h[i]);
}

/* ------------------------------------------------------------------ */
/* Keccak-256 (original Keccak padding 0x01), 32-byte message          */
/* ------------------------------------------------------------------ */
__constant u64 KECCAK_RC[24] = {
    0x0000000000000001UL, 0x0000000000008082UL, 0x800000000000808aUL, 0x8000000080008000UL,
    0x000000000000808bUL, 0x0000000080000001UL, 0x8000000080008081UL, 0x8000000000008009UL,
    0x000000000000008aUL, 0x0000000000000088UL, 0x0000000080008009UL, 0x000000008000000aUL,
    0x000000008000808bUL, 0x800000000000008bUL, 0x8000000000008089UL, 0x8000000000008003UL,
    0x8000000000008002UL, 0x8000000000000080UL, 0x000000000000800aUL, 0x800000008000000aUL,
    0x8000000080008081UL, 0x8000000000008080UL, 0x0000000080000001UL, 0x8000000080008008UL
};
__constant uchar KECCAK_ROT[24] = { 1, 3, 6, 10, 15, 21, 28, 36, 45, 55, 2, 14, 27, 41, 56, 8, 25, 43, 62, 18, 39, 61, 20, 44 };
__constant uchar KECCAK_PI[24]  = { 10, 7, 11, 17, 18, 3, 5, 16, 8, 21, 24, 4, 15, 23, 19, 13, 12, 2, 20, 14, 22, 9, 6, 1 };

static void keccak256_32(const u32 in[8], u32 out[8]) {
    u64 st[25];
    #pragma unroll
    for (int i = 0; i < 25; i++) st[i] = 0UL;
    #pragma unroll
    for (int i = 0; i < 4; i++) st[i] = ((u64)in[2 * i + 1] << 32) | (u64)in[2 * i];
    st[4] = 0x01UL;                       /* padding: 0x01 right after the message */
    st[16] ^= 0x8000000000000000UL;       /* last bit of the 136-byte rate block */

    for (int round = 0; round < 24; round++) {
        u64 bc[5];
        #pragma unroll
        for (int i = 0; i < 5; i++) bc[i] = st[i] ^ st[i + 5] ^ st[i + 10] ^ st[i + 15] ^ st[i + 20];
        #pragma unroll
        for (int i = 0; i < 5; i++) {
            u64 t = bc[(i + 4) % 5] ^ ROTL64(bc[(i + 1) % 5], 1);
            #pragma unroll
            for (int j = 0; j < 25; j += 5) st[j + i] ^= t;
        }
        u64 t = st[1];
        #pragma unroll
        for (int i = 0; i < 24; i++) {
            int j = KECCAK_PI[i];
            u64 tmp = st[j];
            st[j] = ROTL64(t, KECCAK_ROT[i]);
            t = tmp;
        }
        #pragma unroll
        for (int j = 0; j < 25; j += 5) {
            #pragma unroll
            for (int i = 0; i < 5; i++) bc[i] = st[j + i];
            #pragma unroll
            for (int i = 0; i < 5; i++) st[j + i] ^= (~bc[(i + 1) % 5]) & bc[(i + 2) % 5];
        }
        st[0] ^= KECCAK_RC[round];
    }
    #pragma unroll
    for (int i = 0; i < 4; i++) {
        out[2 * i]     = (u32)(st[i]);
        out[2 * i + 1] = (u32)(st[i] >> 32);
    }
}

/* ------------------------------------------------------------------ */
/* CubeHash-16/32-256, 32-byte message                                 */
/* ------------------------------------------------------------------ */
__constant u32 CUBE_IV[32] = {
    0xEA2BD4B4u, 0xCCD6F29Fu, 0x63117E71u, 0x35481EAEu, 0x22512D5Bu, 0xE5D94E63u, 0x7E624131u, 0xF4CC12BEu,
    0xC2D0B696u, 0x42AF2070u, 0xD0720C35u, 0x3361DA8Cu, 0x28CCECA4u, 0x8EF8AD83u, 0x4680AC00u, 0x40E5FBABu,
    0xD89041C3u, 0x6107FBD5u, 0x6C859D41u, 0xF0B26679u, 0x09392549u, 0x5FA25603u, 0x65C892FDu, 0x93CB6285u,
    0x2AF2B5AEu, 0x9E4B4E60u, 0x774ABFDDu, 0x85254725u, 0x15815AEBu, 0x4AB6AAD6u, 0x9CDAF8AFu, 0xD6032C0Au
};

static void cubehash_round(u32 x[32]) {
    #pragma unroll
    for (int i = 0; i < 16; i++) x[i + 16] += x[i];
    #pragma unroll
    for (int i = 0; i < 16; i++) x[i] = ROTL32(x[i], 7);
    #pragma unroll
    for (int i = 0; i < 8; i++) { u32 t = x[i]; x[i] = x[i + 8]; x[i + 8] = t; }
    #pragma unroll
    for (int i = 0; i < 16; i++) x[i] ^= x[i + 16];
    #pragma unroll
    for (int i = 16; i < 32; i += 4) {
        u32 t = x[i];     x[i]     = x[i + 2]; x[i + 2] = t;
        t     = x[i + 1]; x[i + 1] = x[i + 3]; x[i + 3] = t;
    }
    #pragma unroll
    for (int i = 0; i < 16; i++) x[i + 16] += x[i];
    #pragma unroll
    for (int i = 0; i < 16; i++) x[i] = ROTL32(x[i], 11);
    #pragma unroll
    for (int i = 0; i < 16; i += 8) {
        #pragma unroll
        for (int j = 0; j < 4; j++) { u32 t = x[i + j]; x[i + j] = x[i + j + 4]; x[i + j + 4] = t; }
    }
    #pragma unroll
    for (int i = 0; i < 16; i++) x[i] ^= x[i + 16];
    #pragma unroll
    for (int i = 16; i < 32; i += 2) { u32 t = x[i]; x[i] = x[i + 1]; x[i + 1] = t; }
}

static void cubehash256_32(const u32 in[8], u32 out[8]) {
    u32 x[32];
    #pragma unroll
    for (int i = 0; i < 32; i++) x[i] = CUBE_IV[i];

    /* message block (32 bytes) */
    #pragma unroll
    for (int i = 0; i < 8; i++) x[i] ^= in[i];
    for (int r = 0; r < 16; r++) cubehash_round(x);

    /* padding block 0x80 00.. then finalisation */
    x[0] ^= 0x80u;
    for (int r = 0; r < 16; r++) cubehash_round(x);
    x[31] ^= 1u;
    for (int r = 0; r < 160; r++) cubehash_round(x);

    #pragma unroll
    for (int i = 0; i < 8; i++) out[i] = x[i];
}

/* ------------------------------------------------------------------ */
/* Lyra2 (timeCost=1, nRows=4, nCols=4, Blake2b-based sponge)          */
/* ------------------------------------------------------------------ */
#define LYRA_BLOCK 12               /* 768-bit block = 12 x u64 */
#define LYRA_ROW   (LYRA_BLOCK * 4) /* nCols = 4 */

#define LYRA_G(a, b, c, d) do { \
    a += b; d = ROTR64(d ^ a, 32); \
    c += d; b = ROTR64(b ^ c, 24); \
    a += b; d = ROTR64(d ^ a, 16); \
    c += d; b = ROTR64(b ^ c, 63); \
} while (0)

static void lyra_round(u64 v[16]) {
    LYRA_G(v[0], v[4], v[8],  v[12]);
    LYRA_G(v[1], v[5], v[9],  v[13]);
    LYRA_G(v[2], v[6], v[10], v[14]);
    LYRA_G(v[3], v[7], v[11], v[15]);
    LYRA_G(v[0], v[5], v[10], v[15]);
    LYRA_G(v[1], v[6], v[11], v[12]);
    LYRA_G(v[2], v[7], v[8],  v[13]);
    LYRA_G(v[3], v[4], v[9],  v[14]);
}

static void lyra_full(u64 v[16]) {
    #pragma unroll
    for (int r = 0; r < 12; r++) lyra_round(v);
}

/* reducedDuplexRowSetup: out row written in reverse column order */
static void lyra_duplex_setup(u64 st[16], const u64 *rowIn, u64 *rowInOut, u64 *rowOut) {
    for (int c = 0; c < 4; c++) {
        const u64 *pin = rowIn + c * LYRA_BLOCK;
        u64 *pio = rowInOut + c * LYRA_BLOCK;
        u64 *pout = rowOut + (3 - c) * LYRA_BLOCK;
        #pragma unroll
        for (int i = 0; i < LYRA_BLOCK; i++) st[i] ^= (pin[i] + pio[i]);
        lyra_round(st);
        #pragma unroll
        for (int i = 0; i < LYRA_BLOCK; i++) pout[i] = pin[i] ^ st[i];
        #pragma unroll
        for (int i = 0; i < LYRA_BLOCK; i++) pio[i] ^= st[(i + 11) % LYRA_BLOCK];
    }
}

/* reducedDuplexRow: wandering phase, rows can alias (rowInOut == rowOut) */
static void lyra_duplex(u64 st[16], const u64 *rowIn, u64 *rowInOut, u64 *rowOut) {
    for (int c = 0; c < 4; c++) {
        const u64 *pin = rowIn + c * LYRA_BLOCK;
        u64 *pio = rowInOut + c * LYRA_BLOCK;
        u64 *pout = rowOut + c * LYRA_BLOCK;
        #pragma unroll
        for (int i = 0; i < LYRA_BLOCK; i++) st[i] ^= (pin[i] + pio[i]);
        lyra_round(st);
        #pragma unroll
        for (int i = 0; i < LYRA_BLOCK; i++) pout[i] ^= st[i];
        #pragma unroll
        for (int i = 0; i < LYRA_BLOCK; i++) pio[i] ^= st[(i + 11) % LYRA_BLOCK];
    }
}

static void lyra2_4x4(const u32 pwd[8], u32 out[8]) {
    u64 M[4][LYRA_ROW];
    u64 st[16];

    /* sponge init: 8 zero words + Blake2b IV */
    #pragma unroll
    for (int i = 0; i < 8; i++) st[i] = 0UL;
    st[8]  = 0x6a09e667f3bcc908UL; st[9]  = 0xbb67ae8584caa73bUL;
    st[10] = 0x3c6ef372fe94f82bUL; st[11] = 0xa54ff53a5f1d36f1UL;
    st[12] = 0x510e527fade682d1UL; st[13] = 0x9b05688c2b3e6c1fUL;
    st[14] = 0x1f83d9abfb41bd6bUL; st[15] = 0x5be0cd19137e2179UL;

    /* absorb pad(pwd || salt || kLen,pwdLen,saltLen,timeCost,nRows,nCols) = 2 x 64-byte blocks */
    u64 w[4];
    #pragma unroll
    for (int i = 0; i < 4; i++) w[i] = ((u64)pwd[2 * i + 1] << 32) | (u64)pwd[2 * i];
    #pragma unroll
    for (int i = 0; i < 4; i++) { st[i] ^= w[i]; st[i + 4] ^= w[i]; }   /* salt == pwd */
    lyra_full(st);

    st[0] ^= 32UL;                       /* kLen */
    st[1] ^= 32UL;                       /* pwdLen */
    st[2] ^= 32UL;                       /* saltLen */
    st[3] ^= 1UL;                        /* timeCost */
    st[4] ^= 4UL;                        /* nRows */
    st[5] ^= 4UL;                        /* nCols */
    st[6] ^= 0x80UL;                     /* padding start */
    st[7] ^= 0x0100000000000000UL;       /* padding end (byte 127 ^= 0x01) */
    lyra_full(st);

    /* reducedSqueezeRow0: M[0][3-c] = state, reduced round */
    for (int c = 0; c < 4; c++) {
        #pragma unroll
        for (int i = 0; i < LYRA_BLOCK; i++) M[0][(3 - c) * LYRA_BLOCK + i] = st[i];
        lyra_round(st);
    }

    /* reducedDuplexRow1: M[1][3-c] = M[0][c] ^ rand */
    for (int c = 0; c < 4; c++) {
        #pragma unroll
        for (int i = 0; i < LYRA_BLOCK; i++) st[i] ^= M[0][c * LYRA_BLOCK + i];
        lyra_round(st);
        #pragma unroll
        for (int i = 0; i < LYRA_BLOCK; i++) M[1][(3 - c) * LYRA_BLOCK + i] = M[0][c * LYRA_BLOCK + i] ^ st[i];
    }

    /* Setup: row 2 (prev=1, rowa=0), row 3 (prev=2, rowa=1) */
    lyra_duplex_setup(st, M[1], M[0], M[2]);
    lyra_duplex_setup(st, M[2], M[1], M[3]);

    /* Wandering: 4 iterations, row = 0,1,2,3, prev starts at 3 */
    u32 rowa = 0;
    int prev = 3;
    for (int row = 0; row < 4; row++) {
        rowa = (u32)(st[0] & 3UL);
        /* dynamic row selection: copy-free via switch on constant row indices */
        if (rowa == 0)      lyra_duplex(st, M[prev], M[0], M[row]);
        else if (rowa == 1) lyra_duplex(st, M[prev], M[1], M[row]);
        else if (rowa == 2) lyra_duplex(st, M[prev], M[2], M[row]);
        else                lyra_duplex(st, M[prev], M[3], M[row]);
        prev = row;
    }

    /* wrap-up: absorb M[rowa][0] (one 12-word block) with full rounds, squeeze 32 bytes */
    #pragma unroll
    for (int i = 0; i < LYRA_BLOCK; i++) {
        u64 val;
        if (rowa == 0)      val = M[0][i];
        else if (rowa == 1) val = M[1][i];
        else if (rowa == 2) val = M[2][i];
        else                val = M[3][i];
        st[i] ^= val;
    }
    lyra_full(st);

    #pragma unroll
    for (int i = 0; i < 4; i++) {
        out[2 * i]     = (u32)(st[i]);
        out[2 * i + 1] = (u32)(st[i] >> 32);
    }
}

/* ------------------------------------------------------------------ */
/* Skein (Threefish-512 state, 256-bit output), 32-byte message        */
/* ------------------------------------------------------------------ */
__constant u64 SKEIN_IV[8] = {
    0xCCD044A12FDB3E13UL, 0xE83590301A79A9EBUL, 0x55AEA0614F816E6FUL, 0x2A2767A4AE9B94DBUL,
    0xEC06025E74DD7683UL, 0xE7A436CDC4746251UL, 0xC36FBAF9393AD185UL, 0x3EEDBA1833EDFC13UL
};

#define TF_MIX(x0, x1, rc) do { x0 += x1; x1 = ROTL64(x1, rc) ^ x0; } while (0)
#define TF_MIX8(w0, w1, w2, w3, w4, w5, w6, w7, r0, r1, r2, r3) do { \
    TF_MIX(w0, w1, r0); TF_MIX(w2, w3, r1); TF_MIX(w4, w5, r2); TF_MIX(w6, w7, r3); \
} while (0)

static void skein_ubi(u64 h[8], const u64 msg[8], u64 t0, u64 t1) {
    u64 k[9], t[3];
    #pragma unroll
    for (int i = 0; i < 8; i++) k[i] = h[i];
    k[8] = ((k[0] ^ k[1]) ^ (k[2] ^ k[3])) ^ ((k[4] ^ k[5]) ^ (k[6] ^ k[7])) ^ 0x1BD11BDAA9FC1A22UL;
    t[0] = t0; t[1] = t1; t[2] = t0 ^ t1;

    u64 p0 = msg[0], p1 = msg[1], p2 = msg[2], p3 = msg[3];
    u64 p4 = msg[4], p5 = msg[5], p6 = msg[6], p7 = msg[7];

    #pragma unroll
    for (int u = 0; u < 9; u++) {
        int s = 2 * u;
        p0 += k[(s + 0) % 9]; p1 += k[(s + 1) % 9]; p2 += k[(s + 2) % 9]; p3 += k[(s + 3) % 9];
        p4 += k[(s + 4) % 9]; p5 += k[(s + 5) % 9] + t[s % 3];
        p6 += k[(s + 6) % 9] + t[(s + 1) % 3]; p7 += k[(s + 7) % 9] + (u64)s;
        TF_MIX8(p0, p1, p2, p3, p4, p5, p6, p7, 46, 36, 19, 37);
        TF_MIX8(p2, p1, p4, p7, p6, p5, p0, p3, 33, 27, 14, 42);
        TF_MIX8(p4, p1, p6, p3, p0, p5, p2, p7, 17, 49, 36, 39);
        TF_MIX8(p6, p1, p0, p7, p2, p5, p4, p3, 44,  9, 54, 56);

        s = 2 * u + 1;
        p0 += k[(s + 0) % 9]; p1 += k[(s + 1) % 9]; p2 += k[(s + 2) % 9]; p3 += k[(s + 3) % 9];
        p4 += k[(s + 4) % 9]; p5 += k[(s + 5) % 9] + t[s % 3];
        p6 += k[(s + 6) % 9] + t[(s + 1) % 3]; p7 += k[(s + 7) % 9] + (u64)s;
        TF_MIX8(p0, p1, p2, p3, p4, p5, p6, p7, 39, 30, 34, 24);
        TF_MIX8(p2, p1, p4, p7, p6, p5, p0, p3, 13, 50, 10, 17);
        TF_MIX8(p4, p1, p6, p3, p0, p5, p2, p7, 25, 29, 39, 43);
        TF_MIX8(p6, p1, p0, p7, p2, p5, p4, p3,  8, 35, 56, 22);
    }
    /* final key injection, s = 18 */
    p0 += k[0]; p1 += k[1]; p2 += k[2]; p3 += k[3];
    p4 += k[4]; p5 += k[5] + t[0];
    p6 += k[6] + t[1]; p7 += k[7] + 18UL;

    h[0] = msg[0] ^ p0; h[1] = msg[1] ^ p1; h[2] = msg[2] ^ p2; h[3] = msg[3] ^ p3;
    h[4] = msg[4] ^ p4; h[5] = msg[5] ^ p5; h[6] = msg[6] ^ p6; h[7] = msg[7] ^ p7;
}

static void skein256_32(const u32 in[8], u32 out[8]) {
    u64 h[8], m[8];
    #pragma unroll
    for (int i = 0; i < 8; i++) h[i] = SKEIN_IV[i];
    #pragma unroll
    for (int i = 0; i < 4; i++) m[i] = ((u64)in[2 * i + 1] << 32) | (u64)in[2 * i];
    #pragma unroll
    for (int i = 4; i < 8; i++) m[i] = 0UL;
    skein_ubi(h, m, 32UL, 0xF000000000000000UL);       /* type MSG | first | final, 32 bytes */

    #pragma unroll
    for (int i = 0; i < 8; i++) m[i] = 0UL;
    skein_ubi(h, m, 8UL, 0xFF00000000000000UL);        /* type OUT | first | final, counter 0 */

    #pragma unroll
    for (int i = 0; i < 4; i++) {
        out[2 * i]     = (u32)(h[i]);
        out[2 * i + 1] = (u32)(h[i] >> 32);
    }
}

/* ------------------------------------------------------------------ */
/* Blue Midnight Wish 256, 32-byte message                             */
/* ------------------------------------------------------------------ */
#define BMW_SS0(x) (((x) >> 1) ^ ((x) << 3) ^ ROTL32(x,  4) ^ ROTL32(x, 19))
#define BMW_SS1(x) (((x) >> 1) ^ ((x) << 2) ^ ROTL32(x,  8) ^ ROTL32(x, 23))
#define BMW_SS2(x) (((x) >> 2) ^ ((x) << 1) ^ ROTL32(x, 12) ^ ROTL32(x, 25))
#define BMW_SS3(x) (((x) >> 2) ^ ((x) << 2) ^ ROTL32(x, 15) ^ ROTL32(x, 29))
#define BMW_SS4(x) (((x) >> 1) ^ (x))
#define BMW_SS5(x) (((x) >> 2) ^ (x))

__constant uchar BMW_W_IDX[16][5] = {
    {  5,  7, 10, 13, 14 }, {  6,  8, 11, 14, 15 }, {  0,  7,  9, 12, 15 }, {  0,  1,  8, 10, 13 },
    {  1,  2,  9, 11, 14 }, {  3,  2, 10, 12, 15 }, {  4,  0,  3, 11, 13 }, {  1,  4,  5, 12, 14 },
    {  2,  5,  6, 13, 15 }, {  0,  3,  6,  7, 14 }, {  8,  1,  4,  7, 15 }, {  8,  0,  2,  5,  9 },
    {  1,  3,  6,  9, 10 }, {  2,  4,  7, 10, 11 }, {  3,  5,  8, 11, 12 }, { 12,  4,  6,  9, 13 }
};
/* operator applied to terms 1..4 (0 = '+', 1 = '-'); term 0 is always '+' */
__constant uchar BMW_W_SGN[16][4] = {
    { 1, 0, 0, 0 }, { 1, 0, 0, 1 }, { 0, 0, 1, 0 }, { 1, 0, 1, 0 },
    { 0, 0, 1, 1 }, { 1, 0, 1, 0 }, { 1, 1, 1, 0 }, { 1, 1, 1, 1 },
    { 1, 1, 0, 1 }, { 1, 0, 1, 0 }, { 1, 1, 1, 0 }, { 1, 1, 1, 0 },
    { 0, 1, 1, 0 }, { 0, 0, 0, 0 }, { 1, 0, 1, 1 }, { 1, 1, 1, 0 }
};

static u32 bmw_addelt(const u32 M[16], const u32 H[16], int j) {
    return ((ROTL32(M[(j) & 15], ((j) & 15) + 1) +
             ROTL32(M[(j + 3) & 15], ((j + 3) & 15) + 1) -
             ROTL32(M[(j + 10) & 15], ((j + 10) & 15) + 1) +
             (u32)j * 0x05555555u) ^ H[(j + 7) & 15]);
}

static void bmw_compress(const u32 M[16], const u32 H[16], u32 dH[16]) {
    u32 Q[32];
    u32 W[16];

    #pragma unroll
    for (int j = 0; j < 16; j++) {
        u32 acc = M[BMW_W_IDX[j][0]] ^ H[BMW_W_IDX[j][0]];
        #pragma unroll
        for (int k = 1; k < 5; k++) {
            u32 term = M[BMW_W_IDX[j][k]] ^ H[BMW_W_IDX[j][k]];
            acc = BMW_W_SGN[j][k - 1] ? (acc - term) : (acc + term);
        }
        W[j] = acc;
    }
    #pragma unroll
    for (int j = 0; j < 16; j++) {
        u32 s;
        switch (j % 5) {
            case 0:  s = BMW_SS0(W[j]); break;
            case 1:  s = BMW_SS1(W[j]); break;
            case 2:  s = BMW_SS2(W[j]); break;
            case 3:  s = BMW_SS3(W[j]); break;
            default: s = BMW_SS4(W[j]); break;
        }
        Q[j] = s + H[(j + 1) & 15];
    }

    /* expand1 for Q16, Q17 */
    #pragma unroll
    for (int j = 16; j < 18; j++) {
        u32 acc = 0;
        #pragma unroll
        for (int i = 0; i < 16; i++) {
            u32 q = Q[j - 16 + i];
            u32 s;
            switch ((i + 1) & 3) {
                case 0:  s = BMW_SS0(q); break;
                case 1:  s = BMW_SS1(q); break;
                case 2:  s = BMW_SS2(q); break;
                default: s = BMW_SS3(q); break;
            }
            acc += s;
        }
        Q[j] = acc + bmw_addelt(M, H, j - 16 + 16);
    }
    /* expand2 for Q18..Q31 */
    #pragma unroll
    for (int j = 18; j < 32; j++) {
        u32 acc = Q[j - 16] + ROTL32(Q[j - 15], 3) + Q[j - 14] + ROTL32(Q[j - 13], 7) +
                  Q[j - 12] + ROTL32(Q[j - 11], 13) + Q[j - 10] + ROTL32(Q[j - 9], 16) +
                  Q[j - 8] + ROTL32(Q[j - 7], 19) + Q[j - 6] + ROTL32(Q[j - 5], 23) +
                  Q[j - 4] + ROTL32(Q[j - 3], 27) + BMW_SS4(Q[j - 2]) + BMW_SS5(Q[j - 1]);
        Q[j] = acc + bmw_addelt(M, H, j);
    }

    u32 XL = Q[16] ^ Q[17] ^ Q[18] ^ Q[19] ^ Q[20] ^ Q[21] ^ Q[22] ^ Q[23];
    u32 XH = XL ^ Q[24] ^ Q[25] ^ Q[26] ^ Q[27] ^ Q[28] ^ Q[29] ^ Q[30] ^ Q[31];

    dH[0] = ((XH <<  5) ^ (Q[16] >> 5) ^ M[0]) + (XL ^ Q[24] ^ Q[0]);
    dH[1] = ((XH >>  7) ^ (Q[17] << 8) ^ M[1]) + (XL ^ Q[25] ^ Q[1]);
    dH[2] = ((XH >>  5) ^ (Q[18] << 5) ^ M[2]) + (XL ^ Q[26] ^ Q[2]);
    dH[3] = ((XH >>  1) ^ (Q[19] << 5) ^ M[3]) + (XL ^ Q[27] ^ Q[3]);
    dH[4] = ((XH >>  3) ^ Q[20] ^ M[4])        + (XL ^ Q[28] ^ Q[4]);
    dH[5] = ((XH <<  6) ^ (Q[21] >> 6) ^ M[5]) + (XL ^ Q[29] ^ Q[5]);
    dH[6] = ((XH >>  4) ^ (Q[22] << 6) ^ M[6]) + (XL ^ Q[30] ^ Q[6]);
    dH[7] = ((XH >> 11) ^ (Q[23] << 2) ^ M[7]) + (XL ^ Q[31] ^ Q[7]);
    dH[8]  = ROTL32(dH[4],  9) + (XH ^ Q[24] ^ M[8])  + ((XL <<  8) ^ Q[23] ^ Q[8]);
    dH[9]  = ROTL32(dH[5], 10) + (XH ^ Q[25] ^ M[9])  + ((XL >>  6) ^ Q[16] ^ Q[9]);
    dH[10] = ROTL32(dH[6], 11) + (XH ^ Q[26] ^ M[10]) + ((XL <<  6) ^ Q[17] ^ Q[10]);
    dH[11] = ROTL32(dH[7], 12) + (XH ^ Q[27] ^ M[11]) + ((XL <<  4) ^ Q[18] ^ Q[11]);
    dH[12] = ROTL32(dH[0], 13) + (XH ^ Q[28] ^ M[12]) + ((XL >>  3) ^ Q[19] ^ Q[12]);
    dH[13] = ROTL32(dH[1], 14) + (XH ^ Q[29] ^ M[13]) + ((XL >>  4) ^ Q[20] ^ Q[13]);
    dH[14] = ROTL32(dH[2], 15) + (XH ^ Q[30] ^ M[14]) + ((XL >>  7) ^ Q[21] ^ Q[14]);
    dH[15] = ROTL32(dH[3], 16) + (XH ^ Q[31] ^ M[15]) + ((XL >>  2) ^ Q[22] ^ Q[15]);
}

static void bmw256_32(const u32 in[8], u32 out[8]) {
    u32 H[16], M[16], T[16];
    #pragma unroll
    for (int i = 0; i < 16; i++) H[i] = 0x40414243u + (u32)i * 0x04040404u;

    #pragma unroll
    for (int i = 0; i < 8; i++) M[i] = in[i];
    M[8] = 0x80u;
    #pragma unroll
    for (int i = 9; i < 14; i++) M[i] = 0u;
    M[14] = 256u;      /* bit length, low word  */
    M[15] = 0u;        /* bit length, high word */
    bmw_compress(M, H, T);

    #pragma unroll
    for (int i = 0; i < 16; i++) H[i] = 0xaaaaaaa0u + (u32)i;   /* final constants */
    bmw_compress(T, H, M);
    #pragma unroll
    for (int i = 0; i < 8; i++) out[i] = M[8 + i];
}

/* ------------------------------------------------------------------ */
/* Full Lyra2REv2 PoW hash of an 80-byte header (20 LE words)          */
/* ------------------------------------------------------------------ */
static void lyra2rev2_hash(const u32 header[20], u32 out[8]) {
    u32 a[8], b[8];
    blake256_80(header, a);
    keccak256_32(a, b);
    cubehash256_32(b, a);
    lyra2_4x4(a, b);
    skein256_32(b, a);
    cubehash256_32(a, b);
    bmw256_32(b, out);
}

/*
 * Nonce search kernel.
 *   header_prefix : 19 words (76 bytes, little-endian decoded)
 *   target_hi/lo  : the two most significant 32-bit words of the 256-bit target
 *                   (word 7 = most significant, word 6 = next)
 *   found_nonce   : up to 16 winning nonces
 *   found_count   : number of winners (may exceed 16)
 * A hash wins when (hash[7], hash[6]) <= (target_hi, target_lo).
 */
__kernel void search_lyra2v2(
    __constant u32 *header_prefix,
    const u32 base_nonce,
    const u32 target_hi,
    const u32 target_lo,
    __global u32 *found_nonce,
    __global u32 *found_count
) {
    u32 nonce = base_nonce + (u32)get_global_id(0);

    u32 header[20];
    #pragma unroll
    for (int i = 0; i < 19; i++) header[i] = header_prefix[i];
    header[19] = nonce;

    u32 h[8];
    lyra2rev2_hash(header, h);

    if (h[7] < target_hi || (h[7] == target_hi && h[6] <= target_lo)) {
        u32 idx = atomic_inc(found_count);
        if (idx < 16u) found_nonce[idx] = nonce;
    }
}

#ifdef DEBUG_STAGES
/* Test entry: writes the output of every stage (7 x 8 words) for one header. */
__kernel void debug_stages(__constant u32 *header80, __global u32 *out) {
    u32 header[20];
    for (int i = 0; i < 20; i++) header[i] = header80[i];
    u32 a[8], b[8];
    blake256_80(header, a);      for (int i = 0; i < 8; i++) out[0 * 8 + i] = a[i];
    keccak256_32(a, b);          for (int i = 0; i < 8; i++) out[1 * 8 + i] = b[i];
    cubehash256_32(b, a);        for (int i = 0; i < 8; i++) out[2 * 8 + i] = a[i];
    lyra2_4x4(a, b);             for (int i = 0; i < 8; i++) out[3 * 8 + i] = b[i];
    skein256_32(b, a);           for (int i = 0; i < 8; i++) out[4 * 8 + i] = a[i];
    cubehash256_32(a, b);        for (int i = 0; i < 8; i++) out[5 * 8 + i] = b[i];
    bmw256_32(b, a);             for (int i = 0; i < 8; i++) out[6 * 8 + i] = a[i];
}
#endif
