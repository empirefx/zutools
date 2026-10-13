"""Shared crypto/compression primitives for the Zu Online (XinShuShan OL) client.

Everything here was reverse-engineered from the shipped client
(`client.lto`, `d3dx9_24.dll`) and validated against real game data.

  * chacha20_decrypt  - seals the .zu archive headers/tail + LiveUpdateConfig.sys
  * rc4               - the .zu1 data-table cipher (key is a hardcoded 15-byte key)
  * lzo1x_decompress  - the .zu1 data-table compressor (LZO1X)
"""
import struct

# --------------------------------------------------------------------------
# ChaCha20  (used by the RezMgr seal / d3dx9_24.dll proxy)
# Validation vector (all-zero): 76b8e0ada0f13d90405d6ae55386bd28bdd219b8a08ded1aa836efcc8b770dc7
# --------------------------------------------------------------------------
CHACHA_KEY = bytes.fromhex(
    "e70784ff0ede84ef732627e967fbae07fd4ed99a7dddca8f16664cb9e5eeee17")
CHACHA_NONCE = bytes.fromhex("48a63a2be3e374103dd3819e")
_CHACHA_CONST = [0x61707865, 0x3320646e, 0x79622d32, 0x6b206574]


def _rotl(x, n):
    return ((x << n) | (x >> (32 - n))) & 0xffffffff


def _qr(s, a, b, c, d):
    s[a] = (s[a] + s[b]) & 0xffffffff; s[d] = _rotl(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & 0xffffffff; s[b] = _rotl(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b]) & 0xffffffff; s[d] = _rotl(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & 0xffffffff; s[b] = _rotl(s[b] ^ s[c], 7)


def _chacha_block(counter, key=CHACHA_KEY, nonce=CHACHA_NONCE):
    st = (_CHACHA_CONST + list(struct.unpack("<8I", key))
          + [counter & 0xffffffff] + list(struct.unpack("<3I", nonce)))
    w = st[:]
    for _ in range(10):
        _qr(w, 0, 4, 8, 12); _qr(w, 1, 5, 9, 13); _qr(w, 2, 6, 10, 14); _qr(w, 3, 7, 11, 15)
        _qr(w, 0, 5, 10, 15); _qr(w, 1, 6, 11, 12); _qr(w, 2, 7, 8, 13); _qr(w, 3, 4, 9, 14)
    return struct.pack("<16I", *[(w[i] + st[i]) & 0xffffffff for i in range(16)])


def chacha20_decrypt(buf, start_offset, key=CHACHA_KEY, nonce=CHACHA_NONCE):
    """XOR `buf` with the ChaCha20 keystream where buf[0] sits at absolute
    archive offset `start_offset` (counter = start_offset >> 6)."""
    out = bytearray(len(buf))
    c = start_offset >> 6
    sk = start_offset & 63
    i = 0
    while i < len(buf):
        ks = _chacha_block(c, key, nonce)
        n = min(64 - sk, len(buf) - i)
        for j in range(n):
            out[i + j] = buf[i + j] ^ ks[sk + j]
        i += n; c += 1; sk = 0
    return bytes(out)


# --------------------------------------------------------------------------
# RC4  (used inside .zu1 data tables: RC4 then LZO1X)
# --------------------------------------------------------------------------
RC4_KEY = bytes.fromhex("21eff8e89f31d52fd284d8ff0fc3f4")


def rc4(data, key=RC4_KEY):
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xff
        s[i], s[j] = s[j], s[i]
    out = bytearray(len(data))
    i = j = 0
    for k in range(len(data)):
        i = (i + 1) & 0xff
        j = (j + s[i]) & 0xff
        s[i], s[j] = s[j], s[i]
        out[k] = data[k] ^ s[(s[i] + s[j]) & 0xff]
    return bytes(out)


# --------------------------------------------------------------------------
# LZO1X decompressor (standard LZO1X-1 stream)
# --------------------------------------------------------------------------
class LZOError(Exception):
    pass


def lzo1x_decompress(data):
    n = len(data)
    pos = 0
    out = bytearray()
    trailing = 0

    def rd1():
        nonlocal pos
        v = data[pos]; pos += 1
        return v

    def le16():
        nonlocal pos
        v = data[pos] | (data[pos + 1] << 8); pos += 2
        return v

    def lit(length):
        nonlocal pos
        out.extend(data[pos:pos + length]); pos += length

    def zeroes():
        length = 0
        v = rd1()
        while v == 0:
            length += 255
            if length > (1 << 20):
                raise LZOError("too many zeroes")
            v = rd1()
        return length + v

    def match(m_len, m_dist, tr):
        nonlocal trailing
        if m_dist > len(out):
            raise LZOError("distance %d > bufsize %d" % (m_dist, len(out)))
        start = len(out) - m_dist
        if m_dist >= m_len:
            out.extend(out[start:start + m_len])
        else:
            block = bytes(out[start:start + m_dist])
            q, r = divmod(m_len, m_dist)
            out.extend(block * q)
            out.extend(block[:r])
        trailing = tr
        lit(tr)

    def inst(val):
        nonlocal trailing
        if val <= 0x0f:
            if not trailing:
                if val == 0:
                    lit(zeroes() + 18)
                else:
                    lit(val + 3)
            else:
                h = rd1()
                match(2, (h << 2) + (val >> 2) + 1, val & 3)
        elif val <= 0x1f:
            if val & 7 == 0:
                length = 9 + zeroes()
            else:
                length = (val & 7) + 2
            ds = le16()
            dist = 16384 + ((val & 8) >> 3) + (ds >> 2)
            if dist == 16384:
                return False
            match(length, dist, ds & 3)
        elif val <= 0x3f:
            length = val & 31
            if length == 0:
                length = zeroes() + 31
            length += 2
            ds = le16()
            match(length, 1 + (ds >> 2), ds & 3)
        else:
            if val <= 0x7f:
                length = 3 + ((val >> 5) & 1)
            else:
                length = 5 + ((val >> 5) & 3)
            h = rd1()
            match(length, (h << 3) + ((val >> 2) & 7) + 1, val & 3)
        return True

    t = rd1()
    if t == 0x10:
        raise LZOError("LZO v1 stream")
    if t < 0x12:
        if not inst(t):
            return bytes(out)
    else:
        lit(t - 0x11)
    while inst(rd1()):
        pass
    return bytes(out)
