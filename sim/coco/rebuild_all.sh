#!/usr/bin/env bash
# Full clean rebuild: ibm2 shadow + work lib, dependency-ordered via iterative passes.
set -u
cd /tmp/opencode/a2x-sim
A2I=/shared/a2i/rel
ROOT=/home/yanlu/.local/share/opencode/worktree/141aed/a2x-scaffold
O=/shared/oss-cad-suite/bin
W=/tmp/opencode/a2x-sim/wd
rm -rf $W; for l in ibm2 support clib tri unimacro work; do mkdir -p $W/$l; done
F="--std=08 -frelaxed -fsynopsys"
# ibm2: pbi-stripped shadow
for f in std_ulogic_support std_ulogic_unsigned std_ulogic_function_support std_ulogic_ao_support std_ulogic_mux_support; do
  $O/ghdl -a $F --work=ibm --workdir=$W/ibm2 sim_shadow/ibm/$f.vhdl 2>/dev/null || echo "MISS ibm2/$f"
done
# search path
P="-P$W/ibm2"; for l in support clib tri unimacro work; do P="$P -P$W/$l"; done
# support/clib/tri/unimacro (shadow tri/clib)
$O/ghdl -a $F --work=support --workdir=$W/support $ROOT/rel/src/vhdl/support/power_logic_pkg.vhdl 2>/dev/null || echo MISS support
for f in sim_shadow/clib/*.vhdl; do $O/ghdl -a $F --work=clib --workdir=$W/clib $P $f 2>/dev/null || echo "MISS clib/$(basename $f)"; done
$O/ghdl -a $F --work=unimacro --workdir=$W/unimacro $P $ROOT/rel/sim/unimacro/unimacro_vcomp_mock.vhdl 2>/dev/null || echo MISS unimacro1
$O/ghdl -a $F --work=unimacro --workdir=$W/unimacro $P unimacro_sim/bram_tdp_macro_sim.vhdl 2>/dev/null || echo MISS unimacro2
$O/ghdl -a $F --work=tri --workdir=$W/tri $P sim_shadow/tri/tri_latches_pkg.vhdl 2>/dev/null || echo MISS tripkg
for f in $(find sim_shadow/tri -name '*.vhdl' ! -name 'tri_latches_pkg.vhdl' | sort); do $O/ghdl -a $F --work=tri --workdir=$W/tri $P $f 2>/dev/null || echo "MISS tri/$(basename $f)"; done
# work: pkgs first, then iterative passes with done-tracking
DONE=$W/.done; touch $DONE
a(){ f=$1; grep -qx "$f" $DONE && return 0; if $O/ghdl -a $F --work=work --workdir=$W/work $P $f 2>/dev/null; then echo "$f" >> $DONE; else echo "MISS ${f##*/}"; fi; }
for f in $A2I/src/vhdl/work/xuq_pkg.vhdl $A2I/src/vhdl/work/a2x_pkg.vhdl $A2I/src/vhdl/work/iuq_pkg.vhdl; do a $f; done
pass=1; prev=0
while [ $pass -le 10 ]; do
  for f in $(find $A2I/src/vhdl/work -name '*.vhdl' ! -name 'xuq_pkg.vhdl' ! -name 'a2x_pkg.vhdl' ! -name 'iuq_pkg.vhdl' | sort); do
    grep -qx "$f" $DONE || a $f
  done
  n=$(grep -c . $DONE); echo "work pass $pass: $n/223"
  [ "$n" -eq "$prev" ] && break
  prev=$n; pass=$((pass+1))
done
echo "REBUILD DONE: $(grep -c . $DONE) work files"
