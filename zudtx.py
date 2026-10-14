"""LithTech DTX texture / SPR sprite image export (best-effort, pure stdlib).

DTX (version -5, LithTech 2.x):
    bytes 0..4   u16 w, u16 h   (older variant; used when the fields below are 0)
    4..8         i32 version (-5)
    8..12        u16 w, u16 h
    12..16       u32 mipmaps
    16..20       u32 format flags (0x8 = 32-bit, 0x80 bit = alpha, 0x400 = cube)
    26..28       u16 dtx_subformat: 3 = uncompressed, 4/5/6 = DXT1/DXT3/DXT5
    164..        pixel data (base mip level first, then the mip chain)

Only uncompressed 32-bit textures (`dtx_subformat == 3`) are exported, as
24-bit `.bmp` (BGR, alpha dropped). DXT-compressed textures are left alone.
Roughly 92% of the shipped DTX files are uncompressed; the rest are DXT.

SPR is not a bitmap: it is a length-prefixed string table naming the `.dtx`
textures that make up a sprite. It is decoded to a sidecar `.spr.txt` manifest.

Usage:
    python zudtx.py <root>            export under <root> in place
    python zudtx.py --selftest
"""
import struct
import sys
from pathlib import Path

PIXEL_OFFSET = 164
MAX_DIM = 8192


def _read_dtx_header(data):
    """Return (w, h, mipmaps, subformat) or None if not a plain v2 DTX."""
    if len(data) < 28:
        return None
    if struct.unpack_from('<i', data, 4)[0] != -5:
        return None
    w8, h8 = struct.unpack_from('<HH', data, 8)
    w = w8 or struct.unpack_from('<H', data, 0)[0]
    h = h8 or struct.unpack_from('<H', data, 2)[0]
    if not w or not h or w > MAX_DIM or h > MAX_DIM:
        return None
    mipmaps = struct.unpack_from('<I', data, 12)[0]
    subfmt = struct.unpack_from('<H', data, 26)[0]
    return w, h, mipmaps, subfmt


def dtx_to_bmp(dtx_path, bmp_path):
    """Export an uncompressed 32-bit DTX to a 24-bit BMP. Returns True on success."""
    try:
        data = Path(dtx_path).read_bytes()
    except OSError:
        return False
    hdr = _read_dtx_header(data)
    if hdr is None:
        return False
    w, h, _mipmaps, subfmt = hdr
    if subfmt != 3:
        return False
    need = PIXEL_OFFSET + 4 * w * h
    if need > len(data):
        return False
    pix = data[PIXEL_OFFSET:need]
    rowsize = ((w * 3 + 3) // 4) * 4
    size = 54 + rowsize * h
    out = bytearray(size)
    struct.pack_into('<2sIHHI', out, 0, b'BM', size, 0, 0, 54)
    struct.pack_into('<IIIHHIIIIII', out, 14, 40, w, h, 1, 24, 0, rowsize * h, 2835, 2835, 0, 0)
    idx = 54
    for y in range(h - 1, -1, -1):
        row = y * w * 4
        for x in range(w):
            p = row + x * 4
            struct.pack_into('<BBB', out, idx, pix[p], pix[p + 1], pix[p + 2])
            idx += 3
        idx += rowsize - w * 3
    try:
        Path(bmp_path).write_bytes(out)
    except OSError:
        return False
    return True


def spr_to_txt(spr_path, txt_path):
    """Decode an SPR sprite manifest into a text list of referenced textures."""
    try:
        data = Path(spr_path).read_bytes()
    except OSError:
        return False
    off = 20
    names = []
    while off + 2 <= len(data):
        n = struct.unpack_from('<H', data, off)[0]
        off += 2
        if n == 0 or off + n > len(data):
            break
        chunk = data[off:off + n]
        off += n
        try:
            names.append(chunk.decode('ascii'))
        except UnicodeDecodeError:
            return False
    if not names:
        return False
    try:
        Path(txt_path).write_text("\n".join(names) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def convert_dtx(path):
    p = Path(path)
    return dtx_to_bmp(p, p.with_suffix('.bmp')) if p.exists() else False


def convert_spr(path):
    p = Path(path)
    return spr_to_txt(p, p.with_suffix('.spr.txt')) if p.exists() else False


def dumpall(root, outdir=None):
    """Export every DTX under `root` to a sibling .bmp and every SPR to .spr.txt.

    Returns (dtx_count, spr_count). Output always lands next to the source file.
    """
    rootp = Path(root)
    n_dtx = n_spr = 0
    for f in rootp.rglob('*.DTX'):
        if dtx_to_bmp(f, f.with_suffix('.bmp')):
            n_dtx += 1
    for f in rootp.rglob('*.SPR'):
        if spr_to_txt(f, f.with_suffix('.spr.txt')):
            n_spr += 1
    return n_dtx, n_spr


def _mk_dtx(w, h, dims_at_zero=False, subfmt=3):
    hdr = bytearray(PIXEL_OFFSET)
    struct.pack_into('<i', hdr, 4, -5)
    if dims_at_zero:
        struct.pack_into('<HH', hdr, 0, w, h)
    else:
        struct.pack_into('<HH', hdr, 8, w, h)
    struct.pack_into('<I', hdr, 12, 1)
    struct.pack_into('<I', hdr, 16, 0x8)
    struct.pack_into('<H', hdr, 26, subfmt)
    pix = bytearray()
    for i in range(w * h):
        pix += bytes(((i + 1) & 0xFF, (i * 2) & 0xFF, (i * 3) & 0xFF, 0))
    return bytes(hdr) + bytes(pix)


def _selftest():
    import tempfile
    d = Path(tempfile.mkdtemp())
    for dims_at_zero in (False, True):
        name = d / ("z0.DTX" if dims_at_zero else "z8.DTX")
        name.write_bytes(_mk_dtx(2, 3, dims_at_zero))
        assert dtx_to_bmp(name, name.with_suffix('.bmp')), name
        bmp = name.with_suffix('.bmp').read_bytes()
        assert bmp[:2] == b'BM'
        assert struct.unpack_from('<ii', bmp, 18) == (2, 3)
    # compressed variant must be refused
    bad = d / "dxt.DTX"
    bad.write_bytes(_mk_dtx(2, 3, subfmt=6))
    assert dtx_to_bmp(bad, bad.with_suffix('.bmp')) is False
    # SPR manifest
    spr = d / "x.SPR"
    payload = b"spritestex\\a.dtx"
    spr.write_bytes(struct.pack('<II', 1, 15) + b"\x00" * 12 + struct.pack('<H', len(payload)) + payload)
    assert spr_to_txt(spr, d / "x.spr.txt")
    assert "a.dtx" in (d / "x.spr.txt").read_text(encoding="utf-8")
    print("zudtx selftest OK")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--selftest':
        _selftest()
    elif len(sys.argv) > 1:
        d, s = dumpall(sys.argv[1])
        print("exported %d DTX -> bmp, %d SPR -> txt" % (d, s))
