#!/usr/bin/env python3
"""Verify the golden-layer freeze: every Tier-A file must match its manifest
hash; Tier-B files are reported but allowed to be pending/converted."""
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "rel", "src", "vhdl")
MANIFEST = os.path.join(ROOT, "tools", "manifest.sha256")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    if not os.path.exists(MANIFEST):
        sys.stderr.write("no manifest; run: python3 tools/gen_manifest.py > tools/manifest.sha256\n")
        return 2
    bad = 0
    for line in open(MANIFEST):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tier, h, rel, *_ = line.split("\t")
        p = os.path.join(SRC, rel)
        if tier == "A":
            if not os.path.exists(p):
                print(f"MISSING  {rel}")
                bad += 1
            elif sha256(p) != h:
                print(f"MODIFIED {rel}  (golden layer is frozen; create a new provenance version)")
                bad += 1
        else:
            status = "present" if os.path.exists(p) else "pending"
            print(f"tierB {status:9s} {rel}")
    if bad:
        print(f"\n{bad} golden-layer file(s) changed or missing", file=sys.stderr)
        return 1
    print("golden layer intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
