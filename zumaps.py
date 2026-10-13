"""Zu Online `MAPS/` converter: minimaps + heightmaps.

Most `*_HEIGHTMAP.ZU2` use the same container as `.ZU1` (RC4 + LZO1X) wrapping a
1024x1024 16-bit `.bmp`; `*_MINIMAP.ZU3` are raw JPEG. A few files are already
raw (a `.ZU2` holding a bare BMP, say), so the output extension is chosen from
the *content* after unwrapping, not from the name:

    BM     -> .bmp
    ff d8  -> .jpg
    else   -> .bin

Usage:
    python zumaps.py dumpall <mapsdir> <outdir>
    python zumaps.py --selftest
"""
import os
import sys

from zudata import decode_zu1


def convert(path, outdir):
    """Convert one `.ZU2`/`.ZU3` file into `outdir`; returns (outpath, size)."""
    base = os.path.splitext(os.path.basename(path).upper())[0]
    with open(path, "rb") as f:
        data = decode_zu1(f.read())
    if data[:2] == b"BM":
        ext = ".bmp"
    elif data[:2] == b"\xff\xd8":
        ext = ".jpg"
    else:
        ext = ".bin"
    out = os.path.join(outdir, base + ext)
    with open(out, "wb") as o:
        o.write(data)
    return out, len(data)


def dumpall(dirpath, outdir):
    os.makedirs(outdir, exist_ok=True)
    n = 0
    for fn in sorted(os.listdir(dirpath)):
        if fn.upper().endswith((".ZU2", ".ZU3")):
            try:
                out, sz = convert(os.path.join(dirpath, fn), outdir)
                print("[%s] %d bytes -> %s" % (fn, sz, os.path.basename(out)))
                n += 1
            except Exception as e:
                print("[%s] ERROR %s" % (fn, e))
    return n


def _selftest():
    import tempfile
    d = tempfile.mkdtemp()
    jpg = b"\xff\xd8\xff\xe1" + b"\x00" * 32
    bmp = b"BM" + b"\x00" * 32          # raw BMP stored inside a .ZU2
    with open(os.path.join(d, "LEVEL_MINIMAP.ZU3"), "wb") as o:
        o.write(jpg)
    with open(os.path.join(d, "LEVEL_HEIGHTMAP.ZU2"), "wb") as o:
        o.write(bmp)
    out, sz = convert(os.path.join(d, "LEVEL_MINIMAP.ZU3"), d)
    assert out.endswith("LEVEL_MINIMAP.jpg"), out
    assert open(out, "rb").read() == jpg and sz == len(jpg)
    out, sz = convert(os.path.join(d, "LEVEL_HEIGHTMAP.ZU2"), d)
    assert out.endswith("LEVEL_HEIGHTMAP.bmp"), out
    assert open(out, "rb").read() == bmp and sz == len(bmp)
    print("zumaps selftest OK")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        _selftest()
    elif len(sys.argv) > 1 and sys.argv[1] == "dumpall":
        dumpall(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
