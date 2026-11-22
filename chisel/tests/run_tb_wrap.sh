#!/bin/sh
# Run tb_a2i_wrap: verify the generated a2i operand path (rf_op -> ex_op ->
# frac fields -> MSB-swap -> sum+car -> wb fold) numerically against the REAL
# golden fuq_mul, under oss-cad-suite GHDL 7.
#
# Reuses the already-analyzed libraries in sim/coco/.ghdl_wd (fuq_mul is in
# the `work` lib). Re-elaborate (-e) after every -a: `ghdl -r` alone reuses a
# stale elaborated image (that's the "bound check at stale-line-N" gotcha).
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"          # chisel/
WT="$(cd "$HERE/.." && pwd)"                    # worktree root
GHDL=/shared/oss-cad-suite/bin/ghdl
WD="$WT/sim/coco/.ghdl_wd"
P=""
for l in ibm support clib unimacro tri work; do P="$P -P$WD/$l"; done

"$GHDL" -a --std=08 -frelaxed -fsynopsys --workdir="$WD/work" $P --work=work \
    "$HERE/tests/tb_a2i_wrap.vhdl"
"$GHDL" -e --std=08 -frelaxed -fsynopsys --workdir="$WD/work" $P --work=work \
    tb_a2i_wrap
# ghdl -e writes ./tb_a2i_wrap; run it
"$WT/tb_a2i_wrap" 2>/dev/null || (cd "$HERE" && "$GHDL" -r --std=08 -frelaxed \
    -fsynopsys --workdir="$WD/work" $P --work=work tb_a2i_wrap)
