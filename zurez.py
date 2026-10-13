"""RezMgr v1 `.zu` archive reader (ChaCha20-sealed header + LithTech REZ tree).

Usage:
    python zurez.py list  <pack.zu>
    python zurez.py extract <pack.zu> <outdir> [/PREFIX,...]

The archive is a LithTech REZ container whose root directory and a trailing
region are XOR-encrypted with ChaCha20 (see zucrypto). Resource payloads are
stored UNCOMPRESSED; the stored 4-char type is the real extension REVERSED
(e.g. XTD -> DTX, AUL -> LUA, 3UZ -> ZU3, RPS -> SPR).
"""
import os
import struct
import sys

from zucrypto import chacha20_decrypt

# Header layout (all little-endian). Bytes [0x83,0x8b) hold RootDirPos/Size
# and are themselves encrypted; NextWritePos at 0x8f is the seal boundary.
HDR_NEXTWRITE = 0x8f
HDR_ROOTDIR = 0x83
SEAL_TAIL = 8  # archive = data + 8 trailing seal bytes


def _rdstr(b, i):
    j = b.index(b"\x00", i)
    return b[i:j].decode("latin1"), j + 1


def parse_block(b):
    """Parse one REZ block. Returns (entries, consumed).
    dir  entry = ("dir", pos, size, time, name)
    res  entry = ("res", pos, size, time, id, type, name, desc)
    """
    i = 0
    n = len(b)
    ents = []
    while i + 16 <= n:
        mt, pos, sz, tm = struct.unpack_from("<IIII", b, i)
        i += 16
        if mt == 1:
            name, i = _rdstr(b, i)
            ents.append(("dir", pos, sz, tm, name))
        elif mt == 0:
            rid = struct.unpack_from("<I", b, i)[0]; i += 4
            typ = b[i:i + 4].split(b"\x00")[0].decode("latin1"); i += 4
            nk = struct.unpack_from("<I", b, i)[0]; i += 4
            name, i = _rdstr(b, i)
            desc, i = _rdstr(b, i)
            i += 4 * nk
            ents.append(("res", pos, sz, tm, rid, typ, name, desc))
        else:
            break
    return ents, i


class Archive:
    def __init__(self, path):
        self.path = path
        self.size = os.path.getsize(path)
        self._f = open(path, "rb")
        hdr = bytearray(self._f.read(0x100))
        self.nextwrite = struct.unpack_from("<I", hdr, HDR_NEXTWRITE)[0]
        d8 = chacha20_decrypt(bytes(hdr[HDR_ROOTDIR:HDR_ROOTDIR + 8]), HDR_ROOTDIR)
        self.rootpos = struct.unpack_from("<I", d8, 0)[0]
        self._f.seek(self.nextwrite)
        tail = self._f.read(self.size - SEAL_TAIL - self.nextwrite)
        self._tail = chacha20_decrypt(tail, self.nextwrite)

    def _read_block(self, pos, blen):
        if pos >= self.nextwrite:
            o = pos - self.nextwrite
            return self._tail[o:o + blen]
        self._f.seek(pos)
        return self._f.read(blen)

    def entries(self):
        """Yield (path, size, data_reader) for every resource."""
        def walk(pos, blen, path, depth=0):
            if depth > 32:
                return
            ents, _ = parse_block(self._read_block(pos, blen))
            for e in ents:
                if e[0] == "dir":
                    _, dpos, dsz, _tm, name = e
                    if dsz:
                        yield from walk(dpos, dsz, path + "/" + name, depth + 1)
                else:
                    _, rpos, rsz, _tm, _rid, typ, name, _desc = e
                    real = typ[::-1]
                    rel = path + "/" + name + "." + real
                    yield rel, rsz, rpos
        yield from walk(self.rootpos,
                        len(self._tail) - (self.rootpos - self.nextwrite), "")

    def read(self, rpos, rsz):
        return self._read_block(rpos, rsz)

    def close(self):
        self._f.close()


def extract(pack, outdir, prefixes=None, only_ext=None):
    ar = Archive(pack)
    prefixes = tuple(p.upper() for p in prefixes) if prefixes else None
    only_ext = set(e.upper() for e in only_ext) if only_ext else None
    n = 0
    total = 0
    for rel, rsz, rpos in ar.entries():
        up = rel.upper()
        if prefixes and not up.startswith(prefixes):
            continue
        if only_ext and up.rsplit(".", 1)[-1] not in only_ext:
            continue
        dst = os.path.join(outdir, rel.lstrip("/").replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as o:
            o.write(ar.read(rpos, rsz))
        n += 1
        total += rsz
    ar.close()
    print("[%s] files=%d bytes=%d" % (os.path.basename(pack), n, total))


def listing(pack):
    ar = Archive(pack)
    for rel, rsz, rpos in ar.entries():
        print("%s|%d|%d" % (rel, rpos, rsz))
    ar.close()


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "list":
        listing(sys.argv[2])
    elif cmd == "extract":
        pack, outdir = sys.argv[2], sys.argv[3]
        pfx = sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] else None
        extract(pack, outdir, prefixes=pfx)
    else:
        sys.exit(__doc__)
