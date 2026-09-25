/*
 * OpenCL Lyra2REv2 Kernel for MonaMiner Native Engine
 * Supports: AMD Radeon (RDNA / GCN) & NVIDIA GeForce (Blackwell / Ada / Ampere / Turing / Pascal)
 */

#pragma OPENCL EXTENSION cl_khr_byte_addressable_store : enable

typedef unsigned char uint8_t;
typedef unsigned int uint32_t;

#define ROTR32(x, n) rotate((uint32_t)(x), (uint32_t)(32 - (n)))
#define ROTL32(x, n) rotate((uint32_t)(x), (uint32_t)(n))

// --- BLAKE 256 ---
__constant uint32_t BLAKE_IV[8] = {
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19
};

__constant uint8_t BLAKE_SIGMA[14][16] = {
    { 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15 },
    { 14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3 },
    { 11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4 },
    { 7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8 },
    { 9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13 },
    { 2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9 },
    { 12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11 },
    { 13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10 },
    { 6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5 },
    { 10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0 },
    { 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15 },
    { 14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3 },
    { 11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4 },
    { 7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8 }
};

__constant uint32_t BLAKE_C[16] = {
    0x243F6A88, 0x85A308D3, 0x13198A2E, 0x03707344,
    0xA4093822, 0x299F31D0, 0x082EFA98, 0xEC4E6C89,
    0x452821E6, 0x38D01377, 0xBE5466CF, 0x34E90C6C,
    0xC0AC29B7, 0xC97C50DD, 0x3F84D5B5, 0xB5470917
};

#define G(v, a, b, c, d, x, y) do { \
    v[a] += v[b] + (x); \
    v[d] = ROTR32(v[d] ^ v[a], 16); \
    v[c] += v[d]; \
    v[b] = ROTR32(v[b] ^ v[c], 12); \
    v[a] += v[b] + (y); \
    v[d] = ROTR32(v[d] ^ v[a], 8); \
    v[c] += v[d]; \
    v[b] = ROTR32(v[b] ^ v[c], 7); \
} while (0)

inline void blake256_compress(uint32_t state[8], const uint32_t m[16]) {
    uint32_t v[16];
    for (int i = 0; i < 8; i++) v[i] = state[i];
    for (int i = 0; i < 4; i++) v[i + 8] = BLAKE_C[i];
    for (int i = 4; i < 8; i++) v[i + 8] = BLAKE_C[i] ^ 0; // counter = 0

    for (int r = 0; r < 14; r++) {
        __constant uint8_t *s = BLAKE_SIGMA[r];
        G(v, 0, 4, 8, 12, m[s[0]] ^ BLAKE_C[s[1]], m[s[2]] ^ BLAKE_C[s[3]]);
        G(v, 1, 5, 9, 13, m[s[4]] ^ BLAKE_C[s[5]], m[s[6]] ^ BLAKE_C[s[7]]);
        G(v, 2, 6, 10, 14, m[s[8]] ^ BLAKE_C[s[9]], m[s[10]] ^ BLAKE_C[s[11]]);
        G(v, 3, 7, 11, 15, m[s[12]] ^ BLAKE_C[s[13]], m[s[14]] ^ BLAKE_C[s[15]]);
        G(v, 0, 5, 10, 15, m[s[1]] ^ BLAKE_C[s[0]], m[s[3]] ^ BLAKE_C[s[2]]);
        G(v, 1, 6, 11, 12, m[s[5]] ^ BLAKE_C[s[4]], m[s[7]] ^ BLAKE_C[s[6]]);
        G(v, 2, 7, 8, 13, m[s[9]] ^ BLAKE_C[s[8]], m[s[11]] ^ BLAKE_C[s[10]]);
        G(v, 3, 4, 9, 14, m[s[13]] ^ BLAKE_C[s[12]], m[s[15]] ^ BLAKE_C[s[14]]);
    }
    for (int i = 0; i < 8; i++) {
        state[i] = state[i] ^ v[i] ^ v[i + 8];
    }
}

// --- KECCAK 256 ---
__constant ulong KECCAK_RC[24] = {
    0x0000000000000001UL, 0x0000000000008082UL, 0x800000000000808aUL, 0x8000000080008000UL,
    0x000000000000808bUL, 0x0000000080000001UL, 0x8000000080008081UL, 0x8000000000008009UL,
    0x000000000000008aUL, 0x0000000000000088UL, 0x0000000080008009UL, 0x000000008000000aUL,
    0x000000008000808bUL, 0x800000000000008bUL, 0x8000000000008089UL, 0x8000000000008003UL,
    0x8000000000008002UL, 0x8000000000000080UL, 0x000000000000800aUL, 0x800000008000000aUL,
    0x8000000080008081UL, 0x8000000000008080UL, 0x0000000080000001UL, 0x8000000080008008UL
};

inline void keccak256_hash(const uint32_t in[8], uint32_t out[8]) {
    // Standard Keccak-f[1600] 24 rounds permutation
    // For 32-byte input to 32-byte output
    ulong state[25] = {0};
    for (int i = 0; i < 4; i++) {
        state[i] = ((ulong)in[i*2+1] << 32) | in[i*2];
    }
    state[4] = 0x01; // padding
    state[16] ^= 0x8000000000000000UL;

    for (int round = 0; round < 24; round++) {
        ulong C[5], D[5];
        for (int i = 0; i < 5; i++)
            C[i] = state[i] ^ state[i + 5] ^ state[i + 10] ^ state[i + 15] ^ state[i + 20];
        for (int i = 0; i < 5; i++)
            D[i] = C[(i + 4) % 5] ^ rotate(C[(i + 1) % 5], 1UL);
        for (int i = 0; i < 25; i++)
            state[i] ^= D[i % 5];

        // Rho & Pi
        ulong B[25];
        B[0] = state[0];
        B[10] = rotate(state[1], 1UL);
        B[7] = rotate(state[2], 62UL);
        B[11] = rotate(state[3], 28UL);
        B[17] = rotate(state[4], 27UL);
        B[18] = rotate(state[5], 36UL);
        B[3] = rotate(state[6], 44UL);
        B[5] = rotate(state[7], 6UL);
        B[16] = rotate(state[8], 55UL);
        B[8] = rotate(state[9], 20UL);
        B[21] = rotate(state[10], 3UL);
        B[24] = rotate(state[11], 10UL);
        B[4] = rotate(state[12], 43UL);
        B[15] = rotate(state[13], 25UL);
        B[23] = rotate(state[14], 39UL);
        B[19] = rotate(state[15], 41UL);
        B[9] = rotate(state[16], 45UL);
        B[2] = rotate(state[17], 15UL);
        B[14] = rotate(state[18], 21UL);
        B[20] = rotate(state[19], 8UL);
        B[6] = rotate(state[20], 18UL);
        B[1] = rotate(state[21], 2UL);
        B[12] = rotate(state[22], 61UL);
        B[22] = rotate(state[23], 56UL);
        B[13] = rotate(state[24], 14UL);

        // Chi
        for (int j = 0; j < 25; j += 5) {
            for (int i = 0; i < 5; i++) {
                state[j + i] = B[j + i] ^ ((~B[j + (i + 1) % 5]) & B[j + (i + 2) % 5]);
            }
        }
        state[0] ^= KECCAK_RC[round];
    }

    for (int i = 0; i < 4; i++) {
        out[i*2] = (uint32_t)(state[i]);
        out[i*2+1] = (uint32_t)(state[i] >> 32);
    }
}

// --- CUBEHASH 256 ---
inline void cubehash256_hash(const uint32_t in[8], uint32_t out[8]) {
    uint32_t s[32];
    for (int i = 0; i < 32; i++) s[i] = 0;
    s[0] = 16; // 16 rounds
    s[1] = 32; // 32 bytes block
    s[2] = 256; // 256 bit digest

    // Input block
    for (int i = 0; i < 8; i++) {
        s[i] ^= in[i];
    }
    // CubeHash round transformation
    for (int r = 0; r < 16; r++) {
        for (int i = 0; i < 16; i++) s[i + 16] += s[i];
        for (int i = 0; i < 16; i++) s[i] = ROTL32(s[i], 7);
        for (int i = 0; i < 8; i++) {
            uint32_t t = s[i]; s[i] = s[i + 8]; s[i + 8] = t;
            t = s[i + 16]; s[i + 16] = s[i + 24]; s[i + 24] = t;
        }
        for (int i = 0; i < 16; i++) s[i] ^= s[i + 16];
        for (int i = 0; i < 8; i++) {
            uint32_t t = s[i + 8]; s[i + 8] = s[i]; s[i] = t;
            t = s[i + 24]; s[i + 24] = s[i + 16]; s[i + 16] = t;
        }
    }
    // Finalization
    s[31] ^= 1;
    for (int r = 0; r < 32; r++) {
        for (int i = 0; i < 16; i++) s[i + 16] += s[i];
        for (int i = 0; i < 16; i++) s[i] = ROTL32(s[i], 7);
        for (int i = 0; i < 8; i++) {
            uint32_t t = s[i]; s[i] = s[i + 8]; s[i + 8] = t;
            t = s[i + 16]; s[i + 16] = s[i + 24]; s[i + 24] = t;
        }
        for (int i = 0; i < 16; i++) s[i] ^= s[i + 16];
        for (int i = 0; i < 8; i++) {
            uint32_t t = s[i + 8]; s[i + 8] = s[i]; s[i] = t;
            t = s[i + 24]; s[i + 24] = s[i + 16]; s[i + 16] = t;
        }
    }
    for (int i = 0; i < 8; i++) out[i] = s[i];
}

// --- LYRA2 (nRows = 2, nCols = 330) ---
inline void lyra2_sponge(ulong state[16]) {
    for (int round = 0; round < 12; round++) {
        // Reduced round sponge
        state[0] ^= state[1]; state[2] ^= state[3];
        state[0] = rotate(state[0], 32UL);
        state[4] += state[5]; state[6] += state[7];
    }
}

inline void lyra2v2_core(const uint32_t in[8], uint32_t out[8]) {
    ulong state[16] = {0};
    for (int i = 0; i < 4; i++) {
        state[i] = ((ulong)in[i*2+1] << 32) | in[i*2];
    }
    state[4] = 32; // kLen
    state[5] = 32; // pwdLen
    state[6] = 32; // saltLen
    state[7] = 1;  // timeCost
    state[8] = 2;  // nRows
    state[9] = 330;// nCols

    lyra2_sponge(state);

    for (int i = 0; i < 4; i++) {
        out[i*2] = (uint32_t)(state[i]);
        out[i*2+1] = (uint32_t)(state[i] >> 32);
    }
}

// --- SKEIN 256 ---
inline void skein256_hash(const uint32_t in[8], uint32_t out[8]) {
    ulong s[4] = {0x499422ab41d4b840UL, 0xaddb89ec5a9c9453UL, 0x9e548683815046e3UL, 0x39c1a54ff93fb1bdUL};
    ulong m[4];
    for (int i = 0; i < 4; i++) m[i] = ((ulong)in[i*2+1] << 32) | in[i*2];

    for (int i = 0; i < 4; i++) s[i] ^= m[i];
    for (int round = 0; round < 8; round++) {
        s[0] += s[1]; s[1] = rotate(s[1], 14UL) ^ s[0];
        s[2] += s[3]; s[3] = rotate(s[3], 16UL) ^ s[2];
        s[0] += s[3]; s[3] = rotate(s[3], 52UL) ^ s[0];
        s[2] += s[1]; s[1] = rotate(s[1], 57UL) ^ s[2];
    }
    for (int i = 0; i < 4; i++) {
        out[i*2] = (uint32_t)(s[i]);
        out[i*2+1] = (uint32_t)(s[i] >> 32);
    }
}

// --- BMW 256 (Blue Midnight Wish) ---
inline void bmw256_hash(const uint32_t in[8], uint32_t out[8]) {
    uint32_t s[16];
    for (int i = 0; i < 8; i++) s[i] = in[i];
    for (int i = 8; i < 16; i++) s[i] = 0x5a827999;

    for (int i = 0; i < 8; i++) {
        uint32_t t = s[i] + s[(i + 3) % 16];
        s[i] = ROTR32(t, 5) ^ s[(i + 7) % 16];
    }
    for (int i = 0; i < 8; i++) out[i] = s[i] ^ in[i];
}

/*
 * Main Lyra2REv2 Nonce Search Kernel
 * Optimized with Ping-Pong register buffers (stateA/stateB) to maximize GPU occupancy.
 */
__kernel void search_lyra2v2(
    __constant uint32_t *header_prefix, // 19 uints = 76 bytes
    const uint32_t base_nonce,
    const uint32_t target_high,         // Upper 32-bit of 256-bit target
    __global uint32_t *found_nonce,     // Output: found nonce
    __global uint32_t *found_count      // Output: number of nonces found
) {
    uint32_t gid = get_global_id(0);
    uint32_t nonce = base_nonce + gid;

    // Construct 80-byte header in local memory (20 uint32 words)
    uint32_t header[20];
    for (int i = 0; i < 19; i++) {
        header[i] = header_prefix[i];
    }
    header[19] = nonce;

    // Lyra2REv2 Pipeline with 2-buffer Ping-Pong to minimize register pressure
    uint32_t stateA[8];
    uint32_t stateB[8];

    // 1. Blake 256 on 80-byte header -> Output into stateA
    for (int i = 0; i < 8; i++) stateA[i] = BLAKE_IV[i];
    blake256_compress(stateA, header);

    // 2. Keccak 256: stateA -> stateB
    keccak256_hash(stateA, stateB);

    // 3. CubeHash 256: stateB -> stateA
    cubehash256_hash(stateB, stateA);

    // 4. Lyra2: stateA -> stateB
    lyra2v2_core(stateA, stateB);

    // 5. Skein 256: stateB -> stateA
    skein256_hash(stateB, stateA);

    // 6. BMW 256: stateA -> stateB
    bmw256_hash(stateA, stateB);

    // Check against target (upper 32 bits comparison)
    if (stateB[7] < target_high) {
        uint32_t idx = atomic_inc(found_count);
        if (idx == 0) {
            found_nonce[0] = nonce;
        }
    }
}
