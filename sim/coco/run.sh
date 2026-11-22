#!/usr/bin/env bash
# a2x_axi full-core cocotb harness (GHDL 7, oss-cad-suite).
#
# Stages:
#   all        = gen + analyze + elab + sim (default)
#   analyze    = GHDL multi-library analyze only
#   elab       = elaborate a2x_axi (assumes analyze done)
#   sim        = run cocotb against elaborated design
#   clean
#
# Conventions proven by tools/analyze.sh:
#   - per-library --workdir, all -P'd; analyze order ibm support clib unimacro tri work
#   - tri_latches_pkg analyzed first, then tri entities (avoids the
#     component/entity "obsoleted by package" cycle)
#   - work: packages first, then every file with done-file tracking and
#     iterative passes until the set is analyzed (fixpoint, no re-analysis)
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
O=${OSS_BIN:-/shared/oss-cad-suite/bin}
W=${WD:-$ROOT/sim/coco/.ghdl_wd}
T=${T:-/shared/a2i/rel}          # canonical source root (read-only)
CO=$(python3 -c 'from cocotb_tools import config; print(config.lib_entry("vpi","ghdl"))')
export PATH=$O:$PATH
COCOTB_LIB=$(python3 -c 'import cocotb,os;print(os.path.dirname(os.path.dirname(cocotb.__file__)))')/cocotb/libs/libcocotbvpi_ghdl.so
# cocotb 2.x VPI needs GPI_USERS = "<shared libpython.so>;<cocotb.simulator .so>,initialize"
# plus PYGPI_PYTHON_BIN. Resolve the SHARED libpython (LDLIBRARY may be .a).
LIBPY=$(python3 -c 'import sysconfig,glob,os;d=sysconfig.get_config_var("LIBDIR");c=glob.glob(d+"/libpython*.so");print(c[0] if c else d+"/"+sysconfig.get_config_var("LDLIBRARY"))')
SIMSO=$(python3 -c 'import cocotb.simulator; print(cocotb.simulator.__file__)')
export GPI_USERS="$LIBPY;$SIMSO,initialize"
export PYGPI_PYTHON_BIN=$(command -v python3)

for l in ibm support clib tri unimacro work; do mkdir -p "$W/$l"; done
P=""; for l in ibm support clib tri unimacro work; do P="$P -P$W/$l"; done
F="--std=08 -frelaxed -fsynopsys"
DONE="$W/.done"
touch "$DONE"
LOG="$ROOT/sim/coco/sim.log"
[ "${1:-all}" = "sim" ] || : > "$LOG"

a() {  # a <lib> <file>  : analyze one file, done-tracked
  local lib=$1 f=$2
  grep -qx "$f" "$DONE" && return 0
  if $O/ghdl -a $F --work="$lib" --workdir="$W/$lib" $P "$f" >>"$LOG" 2>&1; then
    echo "$f" >> "$DONE"
  else
    echo "MISS ${f##*/} (lib $lib)" | tee -a "$LOG"
    return 0
  fi
}

stage_gen() {
  (cd "$ROOT/sim/coco" && python3 gen_sim_shadow.py >>"$LOG" 2>&1)
}

stage_analyze() {
  # order: ibm -> support -> clib -> unimacro -> tri -> work
  # ibm MUST come from sim_shadow (pin_bit_information stripped) — the canonical
  # copies carry attr-specs that bound-check-fail at elaboration.
  for f in "$ROOT"/sim/coco/sim_shadow/ibm/std_ulogic_support.vhdl \
           "$ROOT"/sim/coco/sim_shadow/ibm/std_ulogic_unsigned.vhdl \
           "$ROOT"/sim/coco/sim_shadow/ibm/std_ulogic_function_support.vhdl \
           "$ROOT"/sim/coco/sim_shadow/ibm/std_ulogic_ao_support.vhdl \
           "$ROOT"/sim/coco/sim_shadow/ibm/std_ulogic_mux_support.vhdl; do a ibm "$f"; done
  a support "$ROOT"/sim/coco/sim_shadow/support/power_logic_pkg.vhdl
  for f in "$ROOT"/sim/coco/sim_shadow/clib/*.vhdl; do a clib "$f"; done
  a unimacro "$T"/sim/unimacro/unimacro_vcomp_mock.vhdl
  a unimacro "$ROOT"/sim/coco/unimacro_sim/bram_tdp_macro_sim.vhdl
  # tri: pkg first (clk_logic), then entities. tri files instantiate each
  # other (e.g. tri_err_rpt -> tri_nlat_scan, tri_serial_scom2 -> tri_err_rpt),
  # so a single alphabetical pass leaves holes — retry until fixpoint like work.
  a tri "$ROOT"/sim/coco/sim_shadow/tri/tri_latches_pkg.vhdl
  local tpass=1 tprev=0 tn=0
  while [ $tpass -le 8 ]; do
    for f in $(find "$ROOT/sim/coco/sim_shadow/tri" -name '*.vhdl' ! -name 'tri_latches_pkg.vhdl' | sort); do
      grep -qx "$f" "$DONE" || a tri "$f"
    done
    tn=$(grep -c "sim_shadow/tri/" "$DONE" || true)
    echo "tri pass $tpass: $tn analyzed" | tee -a "$LOG"
    [ "$tn" -eq "$tprev" ] && break   # fixpoint
    tprev=$tn
    tpass=$((tpass+1))
  done
  # work: pkgs first, then iterate passes re-analyzing whatever GHDL reports
  # stale/obsoleted until a pass has zero pending units. We drive this from
  # GHDL's own errors rather than guessing order: any work file that fails or
  # is named in an 'obsoleted'/'not found' error gets queued next pass.
  for f in "$T"/src/vhdl/work/xuq_pkg.vhdl "$T"/src/vhdl/work/a2x_pkg.vhdl \
           "$T"/src/vhdl/work/iuq_pkg.vhdl; do a work "$f"; done
  local pass=1
  while [ $pass -le 20 ]; do
    : > "$ROOT/sim/coco/.work_err"
    local pend=0
    for f in $(find "$T/src/vhdl/work" -name '*.vhdl' ! -name 'xuq_pkg.vhdl' ! -name 'a2x_pkg.vhdl' ! -name 'iuq_pkg.vhdl' | sort); do
      if ! grep -qx "$f" "$DONE"; then
        pend=$((pend+1))
        a work "$f" || true
      fi
    done
    n=$(grep -c "src/vhdl/work/" "$DONE" || true)
    echo "work pass $pass: $n analyzed, $pend attempted" | tee -a "$LOG"
    [ "$pend" -eq 0 ] && break
    pass=$((pass+1))
  done
  total=$(grep -c . "$DONE" || true)
  echo "ANALYZE DONE: $total files" | tee -a "$LOG"
}

stage_elab() {
  # GHDL flags "X obsoleted by Y" when X's arch was analyzed before Y's entity.
  # Re-analyze the stale units and retry until elab binds cleanly (fixpoint).
  local i u f
  for i in $(seq 1 40); do
    echo "ELAB pass $i" | tee -a "$LOG"
    (cd "$ROOT/sim/coco" && $O/ghdl -e $F --work=work --workdir="$W/work" $P a2x_axi > "$ROOT/sim/coco/elab_last.log" 2>&1) \
      && { cat "$ROOT/sim/coco/elab_last.log" >> "$LOG"; echo "ELAB OK" | tee -a "$LOG"; return 0; }
    cat "$ROOT/sim/coco/elab_last.log" >> "$LOG"
    # stale units: 'architecture "X" ... is obsoleted by' or 'entity "X" ... obsoleted by'
    local obs=$(grep -oP '(architecture|entity|package(?: body)?) "\K[a-z0-9_]+' "$ROOT/sim/coco/elab_last.log" | sort -u)
    [ -z "$obs" ] && { echo "ELAB FAILED (non-obsoletion error; see sim.log)"; exit 1; }
    for u in $obs; do
      f=$(for d in "$T/src/vhdl/work" "$ROOT/sim/coco/sim_shadow/tri" "$ROOT/sim/coco/sim_shadow/clib" "$ROOT/sim/coco/sim_shadow/ibm" "$T/src/vhdl/ibm" "$T/src/vhdl/support"; do
            [ -f "$d/$u.vhdl" ] && { echo "$d/$u.vhdl"; break; }
          done)
      if [ -n "$f" ]; then
        # Only refresh work-library entities/architectures. Packages in
        # ibm/support are stable leaves — re-analyzing them re-obsoletes the
        # whole tree and never converges (and re-imports pin_bit_information
        # if we accidentally hit the canonical copy instead of sim_shadow).
        case "$f" in
          "$T"/src/vhdl/work/*) ;;
          *) echo "  skip pkg refresh $u" >> "$LOG"; continue ;;
        esac
        echo "  refresh $u <- $f" >> "$LOG"
        $O/ghdl -a $F --work=work --workdir="$W/work" $P "$f" >> "$LOG" 2>&1 || true
      fi
    done
  done
  echo "ELAB FAILED (no fixpoint after 40 passes; see sim.log)"; exit 1
}

stage_sim() {
  echo "SIM cocotb" | tee -a "$LOG"
  (cd "$ROOT/sim/coco" && \
    PYTHONPATH="$ROOT/sim/coco" \
    COCOTB_TEST_MODULES=tb \
    COCOTB_TEST_FILTER=${COCOTB_TEST_FILTER:-tb_a2x_axi_tbtop} \
    COCOTB_TOPLEVEL=${COCOTB_TOPLEVEL:-tb_top} \
    COCOTB_TEST_TOPLEVEL=${COCOTB_TOPLEVEL:-tb_top} \
    TOPLEVEL_LANG=vhdl \
    A2X_MAX_CYCLES=${A2X_MAX_CYCLES:-20000} \
    COCOTB_RESULTS_FILE="$ROOT/sim/coco/results.xml" \
    COCOTB_LOG_LEVEL=INFO \
    $O/ghdl -r --work=work ${COCOTB_TOPLEVEL:-tb_top} --ieee-asserts=disable --vpi="$COCOTB_LIB" 2>&1 | tee -a "$LOG")
}

case "${1:-all}" in
  gen)     stage_gen ;;
  analyze) stage_gen; stage_analyze ;;
  elab)    stage_elab ;;
  sim)     stage_sim ;;
  all)     stage_gen; stage_analyze; stage_elab; stage_sim ;;
  clean)   rm -rf "$W" "$ROOT/sim/coco/.ghdl_wd"; rm -f "$LOG" results.xml; exit 0 ;;
  *) echo "usage: run.sh [gen|analyze|elab|sim|all|clean]"; exit 2 ;;
esac
