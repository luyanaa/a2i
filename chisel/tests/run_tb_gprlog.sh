#!/bin/sh
# Run tb_gpralu + tb_log: verify the generated GPR-arith (xuq_alu_add) and
# GPR-logical (xuq_alu) operand paths numerically against the REAL golden
# kernels under oss-cad-suite GHDL 7. Same recipe as run_tb_wrap.sh.
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"          # chisel/
WT="$(cd "$HERE/.." && pwd)"                    # worktree root
GHDL=/shared/oss-cad-suite/bin/ghdl
WD="$WT/sim/coco/.ghdl_wd"
P=""
for l in ibm support clib unimacro tri work; do P="$P -P$WD/$l"; done

for tb in tb_gpralu tb_log; do
  "$GHDL" -a --std=08 -frelaxed -fsynopsys --workdir="$WD/work" $P --work=work \
      "$HERE/tests/$tb.vhdl"
  "$GHDL" -e --std=08 -frelaxed -fsynopsys --workdir="$WD/work" $P --work=work \
      "$tb"
  "$WT/$tb" || (cd "$HERE" && "$GHDL" -r --std=08 -frelaxed -fsynopsys \
      --workdir="$WD/work" $P --work=work "$tb")
done
