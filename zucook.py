"""Post-extraction finalize: convert every wrapped resource to its original format.

After `zurez.extract()` writes the raw archive payloads, `finalize(root)` walks
the tree and turns each wrapped file into something usable:

- `SCRIPT/**/*.LUA` — the `Rar!lua!` DES container is decrypted **in place** to
  plaintext Lua (`zulua`).
- `DATA/*.ZU1` tables -> `.tsv` (or `.bin` when the layout is unknown).
- `WORLDS/*.DAT` -> object/position `.tsv`.
- `MAPS/*` -> `.jpg` / `.bmp`.

Files that are already in their native format (`.DTX`, `.SPR`, `.LTB`, `.WAV`,
`.MP3`, `.JPG`, …) are left untouched. The `Rar!Bute` container
(`FLYSWORDBOOK`/`MISSION3`) is not decoded.

Usage:
    python zucook.py <root>
    python zucook.py --selftest
"""
import os
import sys

import zulua
import zudata
import zuworld
import zumaps


def find_dirs(root, name, exts):
    """Walk `root` for folders called `name` that hold files ending in `exts`."""
    hits = []
    for cur, _dirs, files in os.walk(root):
        if os.path.basename(cur).upper() == name and any(f.upper().endswith(exts) for f in files):
            hits.append(cur)
    return hits


def finalize(root):
    """Normalize every wrapped file under `root` to its original format."""
    zulua.dumpall(root, root)
    for d in find_dirs(root, "DATA", (".ZU1",)):
        zudata.dumpall(d, d)
    for d in find_dirs(root, "WORLDS", (".DAT",)):
        zuworld.dumpall(d, d)
    for d in find_dirs(root, "MAPS", (".ZU2", ".ZU3")):
        zumaps.dumpall(d, d)


def _selftest():
    import struct
    import tempfile

    # find_dirs detection
    tree = os.path.join(tempfile.mkdtemp(), "X")
    for name, ext in (("DATA", ".ZU1"), ("WORLDS", ".DAT"), ("MAPS", ".ZU3")):
        p = os.path.join(tree, name)
        os.makedirs(p)
        open(os.path.join(p, "a" + ext), "wb").close()
    assert find_dirs(tree, "DATA", (".ZU1",)) == [os.path.join(tree, "DATA")]
    assert find_dirs(tree, "WORLDS", (".DAT",)) == [os.path.join(tree, "WORLDS")]
    assert find_dirs(tree, "MAPS", (".ZU2", ".ZU3")) == [os.path.join(tree, "MAPS")]

    # round-trip a Rar!lua! container and check finalize decrypts it in place
    root = tempfile.mkdtemp()
    script = os.path.join(root, "INTERFACE", "SCRIPT")
    os.makedirs(script)
    plain = b"\r\n-- " + "\u4e24\u4e2a".encode("gbk") + b" if (x) then end"
    subs = zulua._key_schedule(zulua.DEFAULT_KEY)
    pad = plain + b"\x00" * (-len(plain) % 8)
    ct = b"".join(zulua._block(pad[i:i + 8], subs, decrypt=False)
                  for i in range(0, len(pad), 8))
    lua_path = os.path.join(script, "TEST.LUA")
    with open(lua_path, "wb") as o:
        o.write(zulua.MAGIC + struct.pack("<I", len(plain)) + ct)

    finalize(root)

    with open(lua_path, "rb") as f:
        assert f.read() == plain, "lua not decrypted in place"
    print("zucook selftest OK")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        _selftest()
    elif len(sys.argv) > 1:
        finalize(sys.argv[1])
    else:
        sys.exit(__doc__)
