"""LithTech Jupiter world `.DAT` reader (WORLDS/*.DAT).

A .DAT is a header (u32 0x55 then a table of u32 section offsets) followed by
streams. The 2nd header offset points at the OBJECT stream:

    object : u16 classlen, class[classlen], u32 propcount
    prop   : u16 namelen, name[namelen],
             value : u8 tag, u32 flags, u16 size, size bytes

Values of interest: "Name" (u16-len string), "Pos"/"Dims" (3 floats xyz),
"Rotation" (4 floats).  Everything else is skipped by its size field.

Usage:
    python zuworld.py list  <file.DAT>
    python zuworld.py dump  <file.DAT> <out.tsv>
    python zuworld.py dumpall <worldsdir> <outdir>
"""
import os
import struct
import sys


def _load(b, i):
    return struct.unpack_from("<I", b, i + 4)[0]  # 2nd header offset = object stream


def _valid_header(b, i, n):
    if i + 8 > n:
        return False
    clen = struct.unpack_from("<H", b, i)[0]
    if not (1 <= clen <= 64) or i + 2 + clen + 4 > n:
        return False
    if not all(32 <= c < 127 for c in b[i + 2:i + 2 + clen]):
        return False
    return struct.unpack_from("<I", b, i + 2 + clen)[0] <= 4096


def parse_objects(b, start):
    """Parse the object stream beginning at `start`. Returns a list of
    (class, {prop: value}) where value is the raw data bytes."""
    i = start
    n = len(b)
    objs = []
    count = struct.unpack_from("<I", b, i)[0]
    i += 4
    if not (0 < count < 100000):
        count = None
    while True:
        if i + 8 > n:
            break
        # per-object records are separated by a u16 marker, and the stream
        # begins with a u32 object count.
        if not _valid_header(b, i, n) and _valid_header(b, i + 2, n):
            i += 2
        if not _valid_header(b, i, n):
            break
        clen = struct.unpack_from("<H", b, i)[0]
        cls = b[i + 2:i + 2 + clen].decode("latin1")
        j = i + 2 + clen
        pcnt = struct.unpack_from("<I", b, j)[0]
        j += 4
        props = {}
        for _ in range(pcnt):
            if j + 2 > n:
                break
            nlen = struct.unpack_from("<H", b, j)[0]
            if not (1 <= nlen <= 64) or j + 2 + nlen + 7 > n:
                break
            nm = b[j + 2:j + 2 + nlen].decode("latin1")
            j += 2 + nlen
            size = struct.unpack_from("<H", b, j + 5)[0]
            j += 7  # u8 tag + u32 flags + u16 size
            if j + size > n:
                break
            props[nm] = b[j:j + size]
            j += size
        objs.append((cls, props))
        i = j
    return objs


def _str(data):
    if len(data) < 2:
        return ""
    ln = struct.unpack_from("<H", data, 0)[0]
    return data[2:2 + ln].decode("latin1", "replace")


def _vec(data, k=3):
    if len(data) < 4 * k:
        return None
    return struct.unpack_from("<%df" % k, data, 0)


def read_dat(path):
    b = open(path, "rb").read()
    start = _load(b, 0)
    return parse_objects(b, start)


def obj_summary(cls, props):
    return {
        "class": cls,
        "name": _str(props.get("Name", b"")),
        "pos": _vec(props.get("Pos", b""), 3),
    }


def dump(path, out_tsv):
    objs = read_dat(path)
    os.makedirs(os.path.dirname(out_tsv) or ".", exist_ok=True)
    with open(out_tsv, "w", encoding="utf-8") as o:
        o.write("class\tname\tx\ty\tz\n")
        for cls, props in objs:
            s = obj_summary(cls, props)
            p = s["pos"] or ("", "", "")
            o.write("%s\t%s\t%s\t%s\t%s\n" % (s["class"], s["name"], p[0], p[1], p[2]))
    print("[%s] objects=%d -> %s" % (os.path.basename(path), len(objs), out_tsv))


def list_classes(path):
    objs = read_dat(path)
    from collections import Counter
    c = Counter(cls for cls, _ in objs)
    print("[%s] objects=%d" % (os.path.basename(path), len(objs)))
    for k, v in c.most_common():
        print("   %-24s %d" % (k, v))


def dumpall(dirpath, outdir):
    os.makedirs(outdir, exist_ok=True)
    for fn in sorted(os.listdir(dirpath)):
        if fn.upper().endswith(".DAT"):
            try:
                dump(os.path.join(dirpath, fn),
                     os.path.join(outdir, os.path.splitext(fn)[0] + ".tsv"))
            except Exception as e:
                print("[%s] ERROR %s" % (fn, e))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "list":
        list_classes(sys.argv[2])
    elif cmd == "dump":
        dump(sys.argv[2], sys.argv[3])
    elif cmd == "dumpall":
        dumpall(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
