#!/usr/bin/env bash
# GHDL multi-library analyze for the A2I golden layer, verified on
# oss-cad-suite GHDL 7 (system ghdl 5 cannot do it).
#
# GHDL quirks handled here:
#   - per-library --workdir must EXIST before analysis
#   - -P must list every library dir that may be referenced
#   - 'tri': tri_latches_pkg declares 22 `component` names identical to tri
#     entities. Analyzing the pkg first makes those entities "obsoleted by
#     package"; analyzing entities first means clk_logic isn't visible. Working
#     recipe = pkg, then each entity file individually in dependency order.
#   - 'work': files have intra-library deps, so feed them one at a time in the
#     precomputed order in tools/frozen_order.txt (deps first).
#   - 'unimacro' supplies RAMB16_*/BRAM_TDP_MACRO entity stubs.
#
# This is intentionally verbose-but-robust; per-file GHDL is slow (~4-6 min for
# the whole frozen set) but reliable. For iteration speed use tools/run.py
# (VUnit) which caches compiled libraries.
set -euo pipefail
A2I=${A2I:-$(cd "$(dirname "$0")/.." && pwd)}
O=${OSS_BIN:-/shared/oss-cad-suite/bin}
W=${WD:-/tmp/opencode/a2x/wd}
for l in ibm support clib tri unimacro work; do mkdir -p "$W/$l"; done
P=""; for l in ibm support clib tri unimacro work; do P="$P -P$W/$l"; done
F="--std=08 -frelaxed"
a(){ $O/ghdl -a $F --work="$1" --workdir="$W/$1" $P "${@:2}" >/dev/null 2>&1 || echo "MISS $1/${2##*/}"; }

a ibm     $A2I/rel/src/vhdl/ibm/std_ulogic_support.vhdl \
          $A2I/rel/src/vhdl/ibm/std_ulogic_unsigned.vhdl \
          $A2I/rel/src/vhdl/ibm/std_ulogic_function_support.vhdl \
          $A2I/rel/src/vhdl/ibm/std_ulogic_ao_support.vhdl \
          $A2I/rel/src/vhdl/ibm/std_ulogic_mux_support.vhdl
a support $A2I/rel/src/vhdl/support/power_logic_pkg.vhdl
a clib    $A2I/rel/src/vhdl/clib/*.vhdl
a unimacro $A2I/rel/sim/unimacro/unimacro_vcomp_mock.vhdl \
           $A2I/rel/sim/unimacro/bram_tdp_macro_mock.vhdl
# tri: pkg first (clk_logic), then entities in dep order.
a tri $A2I/rel/src/vhdl/tri/tri_latches_pkg.vhdl
for f in tri_rlmreg_p tri_rlmlatch_p tri_plat tri_regk tri_regs \
         tri_nlat tri_nlat_scan tri_lcbor tri_lcbnd tri_lcbs \
         tri_direct_err_rpt tri_err_rpt \
         tri_aoi22_nlats tri_aoi22_nlats_wlcb tri_nand2_nlats tri_nor2_nlats tri_oai22_nlats \
         tri_inv_nlats tri_inv_nlats_wlcb \
         tri_cam_16x143_1r1w1c_matchline tri_cam_16x143_1r1w1c \
         tri_cam_32x143_1r1w1c_matchline tri_cam_32x143_1r1w1c \
         tri_lcbcntl_mac tri_lcbcntl_array_mac \
         tri_boltreg_p tri_ser_rlmreg_p tri_slat_scan tri_serial_scom2 \
         tri_cam_parerr_mac tri_psro_soft tri_caa_prism_abist \
         ramb16_s18_s18 ramb16_s36_s36 ramb16_s9_s9 \
         tri_128x16_1r1w_1 tri_128x168_1w_0 tri_144x78_2r2w tri_144x78_2r2w_eco \
         tri_256x162_4w_0 tri_32x35_8w_1r1w tri_512x288_9 \
         tri_64x36_4w_1r1w tri_64x42_4w_1r1w tri_64x72_1r1w tri_bht; do
  a tri "$A2I/rel/src/vhdl/tri/$f.vhdl"
done
# work: packages, then frozen datapath files in dep order.
a work $A2I/rel/src/vhdl/work/xuq_pkg.vhdl $A2I/rel/src/vhdl/work/a2x_pkg.vhdl \
       $A2I/rel/src/vhdl/work/iuq_pkg.vhdl
while read -r f; do
  a work "$A2I/$f"
done < "$A2I/tools/frozen_order.txt"
echo "DONE: $(grep -acE '^\s*entity ' $W/tri/tri-obj08.cf 2>/dev/null) tri, \
$(grep -acE '^\s*entity ' $W/work/work-obj08.cf 2>/dev/null) work entities"

if [ $# -ge 1 ]; then
  unit="$1"
  # Synthesize one unit: give yosys-ghdl its dep files (subset or all).
  files=$(sed 's#^#'"$A2I"'/#' "$A2I/tools/frozen_order.txt" | tr '\n' ' ')
  $O/yosys -m ghdl -p "ghdl $F --workdir=$W/work $P $files -e $unit; synth -top $unit; stat"
fi
