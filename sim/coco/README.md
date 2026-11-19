# a2x_axi full-core cocotb scaffold (GHDL 7)

## Files

- `tb.py` — cocotb bench: 8ns `clk` + 4ns `clk2x`, `reset_n` low 5 cycles then
  released with `thread_stop` 0xF→0x0, `thold='0'`; minimal AXI4 slave on the
  `m00_axi_*` ports (a2l2_axi is the master) with a sparse word memory
  preloaded with a tiny program at the A2I reset PC (0xFFFFFFFC, `b .+0`
  self-loop) plus a magic-address PASS/FAIL store; pass criterion = at least
  one AXI AR (instruction fetch) completes after reset (patterns reused from
  `/shared/a2o/dev/sim/coco/tb.py` + `A2L2.py`).
- `gen_sim_shadow.py` — generates derived sim sources (frozen originals
  untouched):
  - `sim_shadow/{ibm,clib,support,tri}/*.vhdl` — `pin_bit_information`
    attribute *specifications* stripped (they crash GHDL elab/runtime bound
    check; `pbi_t` type decls retained).
  - `unimacro_sim/bram_tdp_macro_sim.vhdl` — the entity-only
    `rel/sim/unimacro/bram_tdp_macro_mock.vhdl` **plus a behavioral TDP-RAM
    architecture** with Xilinx-style INIT_00..7F little-endian preload,
    byte-lane write enables, SRVAL reset (depth = 2**ADDRA'length,
    width = DIA'length, lanes = WEA'length).
- `rebuild_all.sh` — clean multi-library GHDL analyze:
  `ibm2 (pbi-stripped shadow, logical name ibm) -> support -> clib -> unimacro
  -> tri (tri_latches_pkg first, then all entities) -> work (pkgs first, then
  iterative done-tracked passes to fixpoint)`. Flags
  `--std=08 -frelaxed -fsynopsys`, per-library `--workdir`, all dirs `-P`'d.
- `refresh_elab.sh` — obsoletion repair loop: `ghdl -e a2x_axi`; on
  "unit X is obsoleted by Y" errors, re-analyze only the obsoleted units
  (work + tri sources) and retry. Converges in 1–6 iterations.
- `run.sh` — original all-in-one driver (analyze/elab/sim stages).

## Proven flow (exact commands)

```sh
cd sim/coco
# 1) analyze all libraries (pbi-stripped shadows + behavioral BRAM)  ~45 min
bash rebuild_all.sh > rebuild_all.log 2>&1
# 2) finish the ~10 cyclically-instantiated units + elaborate (~few min)
bash refresh_elab.sh > elab_refresh_out.log 2>&1    # prints "ELAB OK"
# 3) run cocotb (NOTE: GPI_USERS must have BOTH libpython and the cocotb
#    pygpi entry point; libpython alone = silent immediate exit)
CO=$(python3 -c 'from cocotb_tools import config; print(config.lib_entry("vpi","ghdl"))')
LP=$(python3 -c "import find_libpython; print(find_libpython.find_libpython())")
PE=$(python3 -c 'from cocotb_tools import config; print(config.pygpi_entry_point())')
GPI_USERS="$LP;$PE" PYGPI_PYTHON_BIN=$(which python3) \
PYTHONPATH=$(python3 -c "import sys;print(':'.join(sys.path))") \
COCOTB_TEST_MODULES=tb COCOTB_TOPLEVEL=a2x_axi \
COCOTB_RESULTS_FILE=$PWD/results.xml COCOTB_LOG_LEVEL=INFO \
  /shared/oss-cad-suite/bin/ghdl -r a2x_axi --vpi=$CO
```

A2I root override: the scripts default to the worktree's own `rel/` copy;
`gen_sim_shadow.py` reads canonical `/shared/a2i/rel` (read-only).

## How far it got (evidence)

- `ELAB OK`: full `a2x_axi` elaborates under GHDL 7.0.0-dev (LLVM, oss-cad
  suite) — 191 MB executable. (see `elab.log`, `elab_refresh_out.log`)
- cocotb attaches via `--vpi=libcocotbvpi_ghdl.so`, clocks generated,
  reset released:
  `40.00ns INFO cocotb.a2x_axi [tb] reset released, threads running`
  (see `sim_run.log`). The behavioral BRAM + AXI slave are exercised by the
  sim (an earlier preload out-of-bounds bug in the BRAM model was found and
  fixed at exactly this stage: `index (2048) out of bounds ... iuq_ic_ierat ...
  ramb16_s9_s9`).
- **RESOLVED — AXI fetch works.** `run.sh sim` (toplevel `tb_top`) →
  `TESTS=1 PASS=1`: `AR 0xFFFFFFF0` at 400ns (first instruction fetch), more
  ARs at 568/720/872ns, `[tb] PASS: 4 AXI transactions` at 920ns.
  The `an_ac_reset_*` tie-off hypothesis above is **disproven** — the real
  blockers were (a) cocotb 2.1 `Clock()` VPI value-writes not generating VHDL
  events under GHDL-LLVM (sim froze ~44ns, so `thread_stop` never released),
  and (b) `m00_axi_arready` undriven (`'U'` poisoned `axi_load_taken`). The
  `tb_top` wrapper generates clk/clk2x/reset/thread_stop natively in VHDL —
  see `tb_top.vhdl` and test `tb_a2x_axi_tbtop` in `tb.py`.

## Notes / gotchas (all verified)

- GHDL 7 (oss-cad) only; system ghdl 5 cannot do this design.
- Analysis of one file at a time with a done-file; failures leave partial
  unit replacements that obsoleted dependents later (source of the endless
  "obsoleted by" cascade) — `refresh_elab.sh` handles it, or use
  `ghdl -m a2x_axi` (it re-analyzes outdated units in dependency order, but
  cannot import never-analyzed files).
- `ghdl -e` needs ALL `-P` dirs; drop the canonical `ibm` dir entirely once
  the `ibm2` shadow exists (logical name `ibm` must resolve to the stripped
  copy or the runtime bound-check on `std_ulogic_support.vhdl:244` returns).
- cocotb 2.1 needs `GPI_USERS="<libpython>;<pygpi entry>"` — one entry only
  → "No GPI_USERS specified, exiting..." or silent exit after 473 t=0
  metavalue warnings.
- A sibling session was concurrently building its own bench (`tb_top`) in
  this same worktree and cleaning `.ghdl_wd/`; the stable build state for
  this harness lives in `/tmp/opencode/a2x-sim` (scripts copied here).
