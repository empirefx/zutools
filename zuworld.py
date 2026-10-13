"""LithTech Jupiter world `.DAT` reader (WORLDS/*.DAT).

Header (from LithTech `PCWorldPacker.cpp`, CURRENT_DAT_VERSION = 85 = 0x55):

    u32 version                       (85)
    u32 object_section_offset         (marker; the object stream starts here)
    u32 blind_data_offset             (= end of object section)
    u32 light_grid_offset             (= end of blind-data section)
    u32 physics_offset                (= end of light-grid section)
    u32 particle_offset               (= end of physics section)
    u32 render_offset                 (= end of particle section)
    u32 reserved[8]                   (zero)
    u32 info_len ; char info[info_len]      (world info / light-table string)
    float pos_min[3] ; float pos_max[3] ; float world_offset[3]

File order of sections: WorldTree, WorldModels (both between the header and the
object section, unmarked), then objects, blind data, light grid, physics,
particle, render.  The object section is bracketed by
`object_section_offset`..`blind_data_offset`.

Object stream:
    u32 object_count, then object_count × [ u16 marker, object ]
    object : u16 classlen, class[classlen], u32 propcount, prop × propcount
    prop   : u16 namelen, name[namelen],
             value : u8 tag, u32 flags, u16 size, size bytes

Values of interest: "Name" (u16-len string), "Pos"/"Dims" (3 floats xyz),
"Rotation" (4 floats).  Everything else is skipped by its size field.

Usage:
    python zuworld.py list  <file.DAT>
    python zuworld.py dump  <file.DAT> <out.tsv>
    python zuworld.py dumpall <worldsdir> <outdir>
    python zuworld.py header <file.DAT>
"""
import os
import struct
import sys

DAT_VERSION = 85


def read_header(b):
    """Parse the `.DAT` header. Returns a dict of all fields + section offsets."""
    version, obj, blind, light, phys, part, rend = struct.unpack_from("<7I", b, 0)
    info_len = struct.unpack_from("<I", b, 60)[0]
    info = b[64:64 + info_len].decode("latin1", "replace")
    p = 64 + info_len
    return {
        "version": version,
        "object_offset": obj, "blind_data_offset": blind,
        "light_grid_offset": light, "physics_offset": phys,
        "particle_offset": part, "render_offset": rend,
        "info": info,
        "pos_min": struct.unpack_from("<3f", b, p),
        "pos_max": struct.unpack_from("<3f", b, p + 12),
        "world_offset": struct.unpack_from("<3f", b, p + 24),
        "header_size": p + 36,
    }


def _load(b, i):
    return struct.unpack_from("<I", b, i + 4)[0]  # object-section offset == 2nd u32


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
    hdr = read_header(b)
    return parse_objects(b, hdr["object_offset"])


def print_header(path):
    b = open(path, "rb").read()
    hdr = read_header(b)
    print("[%s] size=%d version=%d" % (os.path.basename(path), len(b), hdr["version"]))
    for k in ("object", "blind_data", "light_grid", "physics", "particle", "render"):
        print("   %-12s @ 0x%06x" % (k, hdr[k + "_offset"]))
    print("   header_size=%d info=%r" % (hdr["header_size"], hdr["info"][:60]))
    print("   pos_min=%s pos_max=%s world_offset=%s"
          % (hdr["pos_min"], hdr["pos_max"], hdr["world_offset"]))


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
    elif cmd == "header":
        print_header(sys.argv[2])
    else:
        sys.exit(__doc__)
