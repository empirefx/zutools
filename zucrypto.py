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
    """Faithful Python port of lzo1x_decompress_safe (linux/lib/lzo, i.e.
    Markus F.X.J. Oberhumer's LZO1X decoder).  The previous hand-rolled
    version got the decoder's `state` machine wrong (it lacked the
    post-match `next`-literal state), which silently corrupted match runs
    in several data tables.  Raises LZOError unless the stream ends exactly
    on the EOF marker.
    """
    n = len(data)
    ip = 0
    out = bytearray()
    state = 0

    if n < 3:
        raise LZOError("input too short")

    bsv = 0
    if n >= 5 and data[0] == 17:
        bsv = data[1]
        ip = 2

    def u16(a):
        return data[a] | (data[a + 1] << 8)

    if data[ip] > 17:
        t = data[ip] - 17
        ip += 1
        if t < 4:
            state = t                       # match_next with next=t
        out.extend(data[ip:ip + t]); ip += t
        if t >= 4:
            state = 4
    else:
        state = 0

    while True:
        if ip >= n:
            raise LZOError("input exhausted without EOF marker")
        t = data[ip]; ip += 1
        match_len = None
        m_pos = None
        if t < 16:
            if state == 0:
                if t == 0:
                    z = 0
                    while data[ip] == 0:
                        ip += 1; z += 1
                    t += z * 255 + 15 + data[ip]; ip += 1
                t += 3
                if ip + t > n:
                    raise LZOError("literal run past EOF")
                out.extend(data[ip:ip + t]); ip += t
                state = 4
                continue
            elif state != 4:
                next_ = t & 3
                m_pos = len(out) - 1 - (t >> 2) - (data[ip] << 2); ip += 1
                match_len = 2
            else:
                next_ = t & 3
                m_pos = len(out) - 1 - 0x0800 - (t >> 2) - (data[ip] << 2)
                ip += 1
                match_len = 3
        elif t >= 64:
            next_ = t & 3
            m_pos = len(out) - 1 - ((t >> 2) & 7) - (data[ip] << 3); ip += 1
            match_len = (t >> 5) + 1
        elif t >= 32:
            t = (t & 31) + 2
            if t == 2:
                z = 0
                while data[ip] == 0:
                    ip += 1; z += 1
                t += z * 255 + 31 + data[ip]; ip += 1
            m_pos = len(out) - 1
            nxt_l = u16(ip); ip += 2
            m_pos -= nxt_l >> 2
            next_ = nxt_l & 3
            match_len = t
        else:  # 16 <= t < 32
            nxt_peek = u16(ip)
            if (nxt_peek & 0xfffc) == 0xfffc and (t & 0xf8) == 0x18 and bsv:
                # bitstream zero-run
                t &= 7
                t |= data[ip + 2] << 3
                t += 4  # MIN_ZERO_RUN_LENGTH
                out.extend(b"\x00" * t)
                ip += 3
                state = nxt_peek & 3
                out.extend(data[ip:ip + state]); ip += state  # match_next
                continue
            m_pos = len(out) - ((t & 8) << 11)
            t = (t & 7) + 2
            if t == 2:
                z = 0
                while data[ip] == 0:
                    ip += 1; z += 1
                t += z * 255 + 7 + data[ip]; ip += 1
                nxt_peek = u16(ip)
            ip += 2
            m_pos -= nxt_peek >> 2
            next_ = nxt_peek & 3
            match_len = t
            if m_pos == len(out):
                # end marker
                if match_len != 3:
                    raise LZOError("bad EOF marker")
                if ip != n:
                    raise LZOError("trailing input after EOF marker")
                return bytes(out)
            m_pos -= 0x4000

        # -- generic match copy ------------------------------------------------
        if not (m_pos is not None and 0 <= m_pos < len(out)):
            raise LZOError("match distance out of range (: %r)" % (m_pos,))
        if m_pos + match_len > len(out):
            # overlapping copy: replicate forward byte-wise
            pass
        src = m_pos
        for _ in range(match_len):
            out.append(out[src]); src += 1
        # match_next: copy `next_` literal bytes
        if ip + next_ > n:
            raise LZOError("match_next past EOF")
        out.extend(data[ip:ip + next_]); ip += next_
        state = next_
