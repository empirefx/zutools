"""One-shot extraction pipeline: .zu archive(s) -> decoded tables + world TSVs.

Usage:
    python extract_all.py --pack zu_pack1.zu --out extracted\pack1 [--prefix /MAPS,/DATA,/WORLDS]
    python extract_all.py --pack zu_pack1.zu,zu_pack9.zu --out extracted --prefix /DATA,/WORLDS,/MAPS
"""
import argparse
import os
import sys

import zurez
import zudata
import zuworld


def run(pack, out):
    print("== archive", pack)
    zurez.extract(pack, out, prefixes=None)

    data_dirs = []
    worlds_dirs = []
    for root, _dirs, files in os.walk(out):
        b = os.path.basename(root).upper()
        if b == "DATA" and any(f.upper().endswith(".ZU1") for f in files):
            data_dirs.append(root)
        if b == "WORLDS" and any(f.upper().endswith(".DAT") for f in files):
            worlds_dirs.append(root)

    for d in data_dirs:
        print("== zu1 tables", d)
        zudata.dumpall(d, os.path.join(out, "_dump"))
    for d in worlds_dirs:
        print("== world dat", d)
        zuworld.dumpall(d, os.path.join(out, "_world"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True, help="comma-separated .zu paths")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    for p in a.pack.split(","):
        run(p.strip(), os.path.join(a.out, os.path.splitext(os.path.basename(p.strip()))[0])
            if "," in a.pack else a.out)
