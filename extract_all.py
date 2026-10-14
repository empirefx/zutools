r"""One-shot extraction pipeline: .zu archive(s) -> original-format assets.

Extracts each pack, then runs `zucook.finalize` to decrypt Lua and decode
tables / worlds / maps in place.

Usage:
    python extract_all.py --pack zu_pack1.zu --out extracted\pack1
    python extract_all.py --pack zu_pack1.zu,zu_pack9.zu --out extracted
"""
import argparse
import os
import sys

import zurez
import zucook


def run(pack, out):
    print("== archive", pack)
    zurez.extract(pack, out, prefixes=None)
    print("== finalize", out)
    zucook.finalize(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True, help="comma-separated .zu paths")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    for p in a.pack.split(","):
        run(p.strip(), os.path.join(a.out, os.path.splitext(os.path.basename(p.strip()))[0])
            if "," in a.pack else a.out)
