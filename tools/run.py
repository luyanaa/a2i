#!/usr/bin/env python3
"""VUnit harness for the golden-layer scaffold.

Fixes the upstream scripts/run.py path bug and registers a `tb` library for
unit benches so P1 can run focused tests.
"""
import os
from pathlib import Path
from vunit import VUnit

# System ghdl (5.0.1) crashes elaborating clib PIN_BIT_INFORMATION attrs.
# Prefer the oss-cad-suite GHDL 7 which handles them; VUnit picks the backend
# via VUNIT_GHDL_PATH.
if "VUNIT_GHDL_PATH" not in os.environ:
    for cand in ("/shared/oss-cad-suite/bin",):
        if os.path.exists(os.path.join(cand, "ghdl")):
            os.environ["VUNIT_GHDL_PATH"] = cand
            break

_root = Path(__file__).parent.parent
_rel = _root / "rel"
_tb = _root / "tb"

prj = VUnit.from_argv()

# Sim-shadow sources: the frozen ibm/clib libs carry 217 synthesis-only
# `pin_bit_information` attribute specs whose record-aggregate values trip a
# GHDL elaboration bound-check (GHDL5 crashes, GHDL7 errors). Strip only the
# attribute *specification* bodies (the `pbi_t` type decl stays, so downstream
# references still resolve) into a build dir and feed those copies to VUnit.
# Frozen originals in rel/ are untouched.
def _shadow(libName):
    import re
    src_dir = _rel / "src" / "vhdl" / libName
    out_dir = _root / "vunit_out" / "sim_shadow" / libName
    out_dir.mkdir(parents=True, exist_ok=True)
    pat = re.compile(r'attribute\s+pin_bit_information\s+of\s+[^;]+;', re.I | re.S)
    outs = []
    for f in sorted(src_dir.glob("*.vhdl")):
        txt = f.read_text()
        new = pat.sub(lambda m: "-- [sim-shadow] " + m.group(0).replace("\n", "\n-- "), txt)
        dst = out_dir / f.name
        if not dst.exists() or dst.read_text() != new:
            dst.write_text(new)
        outs.append(dst)
    return outs

for libName in ["support", "ibm", "clib", "tri"]:
    prj.add_library(libName).add_source_files(_shadow(libName))

# VUnit refuses a library literally named "work" → top library.
# Only compile the frozen datapath subset (frozen_order.txt, dep-first): the
# full work/ tree has LSU/decode files that are huge and unneeded for unit
# benches, and GHDL7's LLVM backend is slow per-file.
_top = prj.add_library("top")
_order = _root / "tools" / "frozen_order.txt"
if _order.exists():
    for rel in _order.read_text().split():
        if rel:
            _top.add_source_file(_root / rel)
else:
    _top.add_source_files(_rel / "src" / "vhdl" / "work" / "*.vhdl")
prj.add_library("unimacro").add_source_files(_rel / "sim" / "unimacro" / "*.vhdl")
if _tb.exists():
    prj.add_library("tb").add_source_files(_tb / "*.vhdl")

prj.set_compile_option("ghdl.a_flags", ["-frelaxed", "-fsynopsys"])
# clib/ibm cells carry synthesis-only PIN_BIT_INFORMATION attributes guarded by
# `synopsys translate_off/on` pragmas. GHDL5's mcode crashes on them; GHDL7
# elaborates them as real (bounded) expressions unless -fsynopsys makes it skip
# the pragma'd regions. -frelaxed covers the remaining legacy constructs.
prj.set_sim_option("ghdl.elab_flags", ["-frelaxed", "-fsynopsys"])
prj.main()
