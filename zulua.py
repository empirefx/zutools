"""Zu Online Lua script decryptor.

Container:  b"Rar!lua!" | u32 orig_size | ciphertext (padded to 8 bytes)
Cipher:     a DES implementation with client-specific permutation tables
            (dumped from client.lto; see docs/FORMATS.md).  ECB, decrypt.

Usage:
    python zulua.py decode <in.LUA> <out.lua>
    python zulua.py dumpall <indir> <outdir>
"""
import os
import struct
import sys

import zulua_tables as T

MAGIC = b"Rar!lua!"
DEFAULT_KEY = b"BUF12SIZ"


def _rol(v, n):
    return ((v << n) | (v >> (32 - n))) & 0xFFFFFFFF


def _expand(tab, idx):
    v = 0
    for k in range(8):
        v |= tab[idx[k]]
        if k != 7:
            v >>= 1
    return v


def _key_schedule(key8):
    C = D = 0
    p = 0
    for i in range(8):
        kb = key8[i]
        for _ in range(7):
            if kb & 0x80:
                t = T.PC1[p]
                if t >= 0x1C:
                    D |= 1 << (t - 0x1C)
                else:
                    C |= 1 << t
            p += 1
            kb = (kb << 1) & 0xFF
    subs = []
    for r in range(16):
        s = T.KB[r]
        C = ((C << s) | (C >> (28 - s))) & 0xFFFFFFF
        D = ((D << s) | (D >> (28 - s))) & 0xFFFFFFF
        b = [0] * 8
        pa = 0
        for i in range(4):
            byte = 0
            mask = 0x20
            while mask:
                if (D >> T.PC2A[pa]) & 1:
                    byte |= mask
                pa += 1
                mask >>= 1
            b[i] = byte
        pb = 0
        for i in range(4):
            byte = 0
            mask = 0x20
            while mask:
                if (C >> T.PC2B[pb]) & 1:
                    byte |= mask
                pb += 1
                mask >>= 1
            b[4 + i] = byte
        v0 = (b[0] << 24) | (b[2] << 16) | (b[4] << 8) | b[6]
        v1 = (b[1] << 24) | (b[3] << 16) | (b[5] << 8) | b[7]
        subs.append((v0, v1))
    return subs


def _block(block, subs, decrypt):
    reg4 = _expand(T.IP, block)
    reg8 = _expand(T.IP2, block)
    order = range(15, -1, -1) if decrypt else range(16)
    for idx in order:
        sk0, sk1 = subs[idx]
        new = _feistel_result(reg4, reg8, sk0, sk1)
        reg4 = reg8
        reg8 = new
    pc = _pack(T.FP, reg8, reg4)
    pd = _pack(T.FP2, reg8, reg4)
    return bytes([(pc >> 24) & 0xFF, (pc >> 16) & 0xFF, (pc >> 8) & 0xFF, pc & 0xFF,
                  (pd >> 24) & 0xFF, (pd >> 16) & 0xFF, (pd >> 8) & 0xFF, pd & 0xFF])


def _feistel_result(reg4, reg8, sk0, sk1):
    a = _rol(reg8, 1)
    t1 = a ^ sk1
    t0 = _rol(a, 28) ^ sk0
    res = reg4
    res ^= T.SP[7][t1 & 0x3F]
    res ^= T.SP[5][(t1 >> 8) & 0x3F]
    res ^= T.SP[3][(t1 >> 16) & 0x3F]
    res ^= T.SP[1][(t1 >> 24) & 0x3F]
    res ^= T.SP[6][t0 & 0x3F]
    res ^= T.SP[4][(t0 >> 8) & 0x3F]
    res ^= T.SP[2][(t0 >> 16) & 0x3F]
    res ^= T.SP[0][(t0 >> 24) & 0x3F]
    return res & 0xFFFFFFFF


def _pack(tab, reg8, reg4):
    v = 0
    for k in range(8):
        reg = reg8 if k % 2 == 0 else reg4
        v |= tab[(reg >> (8 * (k // 2))) & 0xFF]
        if k != 7:
            v >>= 1
    return v


def decrypt_blob(blob, key=DEFAULT_KEY):
    """blob = full file bytes.  Returns the plaintext Lua source."""
    if blob[:8] != MAGIC:
        return blob
    usize = struct.unpack_from("<I", blob, 8)[0]
    subs = _key_schedule(key)
    data = blob[12:]
    out = bytearray()
    for i in range(0, len(data), 8):
        out += _block(data[i:i + 8], subs, decrypt=True)
    return bytes(out[:usize])


def read(path, key=DEFAULT_KEY):
    with open(path, "rb") as f:
        return decrypt_blob(f.read(), key)


def dumpall(indir, outdir):
    os.makedirs(outdir, exist_ok=True)
    n = 0
    for root, _dirs, files in os.walk(indir):
        for fn in files:
            if not fn.upper().endswith(".LUA"):
                continue
            src = os.path.join(root, fn)
            blob = open(src, "rb").read()
            if blob[:8] != MAGIC:
                continue
            out = os.path.join(outdir, os.path.relpath(src, indir))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "wb").write(decrypt_blob(blob))
            n += 1
    print("decrypted", n, "lua files ->", outdir)


def _selftest():
    # first block of SCRIPT/BM_A003.LUA: ct -> "\r\n--" + GBK for "两个"
    ct = bytes.fromhex("b76acb4abc906c17")
    pt = b"\r\n--" + "\u4e24\u4e2a".encode("gbk")
    subs = _key_schedule(DEFAULT_KEY)
    assert _block(ct, subs, decrypt=True) == pt, "DES decrypt mismatch"
    assert _block(pt, subs, decrypt=False) == ct, "DES encrypt mismatch"
    print("zulua selftest OK")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _selftest()
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "decode":
        import ast
        key = ast.literal_eval(sys.argv[4]) if len(sys.argv) > 4 else DEFAULT_KEY
        out = read(sys.argv[2], key)
        open(sys.argv[3], "wb").write(out)
        print("wrote", len(out), "bytes")
    elif cmd == "dumpall":
        dumpall(sys.argv[2], sys.argv[3])
