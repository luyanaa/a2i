"""emit.py — top-level: pick a profile + kernel, emit Verilog.

    python3 -m amcore.emit --profile a2i --fu fuq_mul -o build/a2i_fuq_mul.v
    python3 -m amcore.emit --profile a2o --fu fuq_mul -o build/a2o_fuq_mul.v

The generated Verilog instantiates the frozen kernel as a named blackbox
(`fuq_mul`, etc.); the golden VHDL/Verilog is compiled/linked separately and
bound at elaboration by the simulator or synthesis tool.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from amaranth.back import verilog

PROFILES = {}


def _profiles():
    global PROFILES
    if not PROFILES:
        from .profiles import InOrderCore, OoOCore
        PROFILES = {"a2i": InOrderCore, "a2o": OoOCore}
    return PROFILES


def build(profile: str, fu: str):
    cls = _profiles()[profile]
    return cls(fu_kernel=fu)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Amaranth CPU IP generator")
    ap.add_argument("--profile", choices=list(_profiles()), default="a2i")
    ap.add_argument("--fu", default="fuq_mul", help="EX-stage kernel entity")
    ap.add_argument("-o", "--out", help="output .v (default stdout)")
    ns = ap.parse_args(argv)
    top = build(ns.profile, ns.fu)
    v = verilog.convert(top, ports=top.ports() if hasattr(top, "ports") else None,
                        name=ns.fu if False else f"{ns.profile}_{ns.fu}")
    if ns.out:
        Path(ns.out).parent.mkdir(parents=True, exist_ok=True)
        Path(ns.out).write_text(v)
        print(f"wrote {ns.out}")
    else:
        print(v)


if __name__ == "__main__":
    main()
