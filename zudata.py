"""Zu Online `.zu1` data-table decoder + dumper.

Container:  u32 magic=0x2121cafd ("FDCA2121") | u32 flags | u32 orig_size | payload
payload  = RC4(15-byte key) then LZO1X.  Files whose first 4 bytes are NOT the
magic are plaintext tables (magic == record count).

Usage:
    python zudata.py decode <in.ZU1> <out.bin>
    python zudata.py dump   <in.ZU1> <outdir>
    python zudata.py dumpall <datadir> <outdir>
"""
import os
import sys

from zucrypto import rc4, lzo1x_decompress

ZU1_MAGIC = b"\xfd\xca\x21\x21"


def decode_zu1(blob):
    if blob[:4] == ZU1_MAGIC:
        usize = int.from_bytes(blob[8:12], "little")
        out = lzo1x_decompress(rc4(blob[12:]))
        return out
    return blob


def read_zu1(path):
    with open(path, "rb") as f:
        return decode_zu1(f.read())


def _s(b):
    z = b.find(b"\x00")
    if z >= 0:
        b = b[:z]
    try:
        return b.decode("gbk")
    except UnicodeDecodeError:
        return b.decode("latin1")


# Field layouts: name -> (hdr, [ (offset, label) ]) describing a fixed-size
# record where strings/ints sit at fixed offsets.  Record count = u32 @0.
LAYOUTS = {
    "OBJS.ZU1": (4, [(0, "id"), (4, "name"), (30, "title"), (56, "icon")]),
    "OBJS2.ZU1": (4, [(0, "id"), (4, "name"), (30, "title"), (56, "icon")]),
    "OBJS3.ZU1": (4, [(0, "id"), (4, "name"), (30, "title"), (56, "icon")]),
    "WORLDMAPMISSION.ZU1": (4, [(0, "id"), (4, "name"), (132, "name2")]),
    "TITLE.ZU1": (4, [(0, "id"), (4, "name"), (37, "desc"),
                      (318, "requirement"), (575, "effect")]),
}

# Tables whose records are "u32 id + name string at a fixed offset".
# Layouts beyond the name are not yet mapped (the rest of each record is raw).
_NAME_AT = {
    "ACTIONS.ZU1": 4, "ACTDETAILINFO.ZU1": 4, "ACTDETAILINFO2.ZU1": 4,
    "ACTTYPEINFO.ZU1": 4, "CAVERNTEMPLATE.ZU1": 4, "CHATFACE.ZU1": 4,
    "CHATFACE2.ZU1": 4, "FORMULA.ZU1": 4, "GUILDDEVELOPMENT.ZU1": 4,
    "GUILDTECHNOLOGY.ZU1": 4, "GUILDTEMPLATE.ZU1": 4, "LIVESKILL.ZU1": 4,
    "LIVESPELLMAKE.ZU1": 4, "LOADING.ZU1": 4, "MAPS.ZU1": 4, "MOTION.ZU1": 4,
    "MUSICINFO.ZU1": 4, "NOBLETEMPLATE.ZU1": 4, "REFINE.ZU1": 4,
    "REFINE2.ZU1": 4, "REFINE3.ZU1": 4, "SPEATTEX.ZU1": 4, "SPEATTEX2.ZU1": 4,
    "SPELLSEX.ZU1": 4, "STONETABLE.ZU1": 4, "SUITATTRIBUTEINTRO.ZU1": 4,
    "TALENTS.ZU1": 4, "TIPS.ZU1": 4, "ITEMS.ZU1": 4, "ITEMS2.ZU1": 4,
    "ITEMS3.ZU1": 4, "ITEMS.1.00.05.ZU1": 4, "SPELL.ZU1": 8, "SPELLS.ZU1": 8,
    "ITEMATT.ZU1": 8,
}
for _n, _o in _NAME_AT.items():
    LAYOUTS[_n] = (4, [(0, "id"), (_o, "name")])

# Plaintext config/script tables (already-decoded bytes are the file content).
TEXT_TABLES = {
    "CREED.ZU1": ".xml", "ERROR.ZU1": ".txt", "ERROR2.ZU1": ".txt",
    "ERROR3.ZU1": ".txt", "FLIGHT.ZU1": ".ini", "GMHELP.ZU1": ".ini",
    "HELPMANAGED.ZU1": ".ini", "MISSION.ZU1": ".ini", "SHOPCITYHELP.ZU1": ".ini",
    "STORYCARD.ZU1": ".ini", "TUTORIAL.ZU1": ".txt",
}


def dump_records(blob, hdr, fields, out_tsv):
    cnt = int.from_bytes(blob[:4], "little")
    recsize = (len(blob) - 4) // cnt if cnt else 0
    with open(out_tsv, "w", encoding="utf-8") as o:
        o.write("\t".join(["idx"] + [f[1] for f in fields]) + "\n")
        for i in range(cnt):
            rec = blob[4 + i * recsize:4 + (i + 1) * recsize]
            row = [str(i)]
            for off, _lab in fields:
                if off + 4 <= len(rec) and _lab == "id":
                    row.append(str(int.from_bytes(rec[off:off + 4], "little")))
                else:
                    row.append(_s(rec[off:off + 200]).replace("\t", " "))
            o.write("\t".join(row) + "\n")
    return cnt, recsize


def dump_keyworddata(blob, out_tsv):
    hdr = 24
    fsz = 255
    nf = 11
    recsize = hdr + nf * fsz
    cnt = int.from_bytes(blob[:4], "little")
    cnt = (len(blob) - 4) // recsize
    with open(out_tsv, "w", encoding="utf-8") as o:
        o.write("idx\tcoord\tname\tf1\tf2\tf3\tf4\tf5\tf6\tf7\tf8\tf9\n")
        for i in range(cnt):
            rec = blob[4 + i * recsize:4 + (i + 1) * recsize]
            vals = []
            for k in range(nf):
                vals.append(_s(rec[hdr + k * fsz:hdr + (k + 1) * fsz]).replace("\t", " "))
            o.write("\t".join([str(i), vals[0], vals[10]] + vals[1:10]) + "\n")
    return cnt, recsize


def dump_resource(blob, out_tsv):
    """RESOURCE.ZU1: a filesystem-path list. The per-record framing is not fully
    stable (id/type/length header + name), so extract the path strings directly."""
    import re
    names = [m for m in re.findall(r"[\x20-\x7e]{4,}", blob.decode("latin1"))
             if "\\" in m]
    with open(out_tsv, "w", encoding="utf-8") as o:
        o.write("idx\tname\n")
        for i, nm in enumerate(names):
            o.write("%d\t%s\n" % (i, nm))
    return len(names)


def dump(path, outdir):
    os.makedirs(outdir, exist_ok=True)
    name = os.path.basename(path).upper()
    blob = read_zu1(path)
    base = os.path.splitext(name)[0]
    if name == "KEYWORDDATA.ZU1":
        cnt, rs = dump_keyworddata(blob, os.path.join(outdir, base + ".tsv"))
    elif name == "RESOURCE.ZU1":
        cnt = dump_resource(blob, os.path.join(outdir, base + ".tsv"))
        rs = len(blob) // cnt if cnt else 0
    elif name in LAYOUTS:
        hdr, fields = LAYOUTS[name]
        cnt, rs = dump_records(blob, hdr, fields, os.path.join(outdir, base + ".tsv"))
    elif name in TEXT_TABLES:
        with open(os.path.join(outdir, base + TEXT_TABLES[name]), "wb") as o:
            o.write(blob)
        print("[%s] decoded %d bytes -> %s%s" % (name, len(blob), base, TEXT_TABLES[name]))
        return
    else:
        with open(os.path.join(outdir, base + ".bin"), "wb") as o:
            o.write(blob)
        print("[%s] decoded %d bytes (no layout, wrote .bin)" % (name, len(blob)))
        return
    print("[%s] rows=%d recsize=%d -> %s.tsv" % (name, cnt, rs, base))


def dumpall(datadir, outdir):
    for fn in sorted(os.listdir(datadir)):
        if fn.upper().endswith(".ZU1"):
            try:
                dump(os.path.join(datadir, fn), outdir)
            except Exception as e:
                print("[%s] ERROR %s" % (fn, e))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "decode":
        blob = read_zu1(sys.argv[2])
        with open(sys.argv[3], "wb") as o:
            o.write(blob)
        print("decoded", len(blob), "bytes")
    elif cmd == "dump":
        dump(sys.argv[2], sys.argv[3])
    elif cmd == "dumpall":
        dumpall(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
