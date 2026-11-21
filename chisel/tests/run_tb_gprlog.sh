#!/bin/sh
# Run the GPR kernel benches: verify the generated operand paths for\n# xuq_alu_add (arith), xuq_alu (logicals + mul), and xuq_agen (EA)\n# numerically against the REAL golden kernels under oss-cad-suite GHDL 7.
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"          # chisel/
WT="$(cd "$HERE/.." && pwd)"                    # worktree root
GHDL=/shared/oss-cad-suite/bin/ghdl
WD="$WT/sim/coco/.ghdl_wd"
P=""
for l in ibm support clib unimacro tri work; do P="$P -P$WD/$l"; done

for tb in tb_gpralu tb_log tb_agen tb_alumul; do
  "$GHDL" -a --std=08 -frelaxed -fsynopsys --workdir="$WD/work" $P --work=work \
      "$HERE/tests/$tb.vhdl"
  "$GHDL" -e --std=08 -frelaxed -fsynopsys --workdir="$WD/work" $P --work=work \
      "$tb"
  "$WT/$tb" || (cd "$HERE" && "$GHDL" -r --std=08 -frelaxed -fsynopsys \
      --workdir="$WD/work" $P --work=work "$tb")
done
