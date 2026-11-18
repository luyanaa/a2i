# a2x scaffold — P0 freeze + build skeleton

Tracks the refactor that freezes silicon-proven A2I datapath leaf kernels and
re-implements control/ISA in a Chisel CPU IP generator. **P0 only: no RTL is
modified.**

## Layout

- `tools/gen_manifest.py` — emits `tools/manifest.sha256` (Tier-A frozen +
  Tier-B pending). Source of truth for the freeze boundary.
- `tools/check_manifest.py` — CI gate; fails if any Tier-A file changes.
- `tools/analyze.sh` — reproducible GHDL-7 + Yosys analyze/synth for the
  golden layer (handles GHDL library-order and component/entity quirks).
- `tools/run.py` — VUnit harness (fixes upstream `scripts/run.py` path bug,
  adds `tb` library). Points VUnit at oss-cad **GHDL 7** (`VUNIT_GHDL_PATH`),
  scopes the `top` library to `tools/frozen_order.txt`, and generates
  **sim-shadow** copies of `ibm/clib/support/tri` under `vunit_out/sim_shadow/`
  with the 217 synthesis-only `pin_bit_information` attribute *specs* stripped
  (they trip a GHDL elab bound-check; frozen originals untouched). Flags:
  `-frelaxed -fsynopsys` at analyze **and** elab.
- `golden/` — frozen-layer notes; canonical VHDL stays under `rel/src/vhdl/`.
- `tb/` — VUnit unit benches (P1; start with `fuq_mul`).
- `chisel/` — CPU IP generator (P2+).
- `sim/coco/` — cocotb full-core bench (P3).

## Verified so far (all reproducible)

- `tools/check_manifest.py` → `golden layer intact` (149 Tier-A entries).
- `tools/analyze.sh` → analyzes the full frozen closure into GHDL libraries:
  46/46 tri entities + 84/84 work entities (all `fuq_*` and `xuq_*` datapath
  units). Handles the `tri_latches_pkg` component/entity cycle and `xuq_pkg`
  ordering automatically.
- GHDL→Yosys synth end-to-end on the three datapath tops:
  - `fuq_mul`  (FPU multiplier): 15,229 cells, `m92_2/m92_1/m62` submodules
  - `xuq_alu`  (ALU): full cell mix, `expand_type=1` pure-RTL latches
  - `xuq_agen` (address generation): clean
  (each via `tools/analyze.sh <unit>`; BRAM macro stubs come from `unimacro`)

## Frozen boundary (Tier-A)

FPU leaf: `fuq_alg*`, `fuq_add*`, `fuq_nrm*`, `fuq_lza*`, `fuq_lze`,
`fuq_hc16pp*`, `fuq_csa22_h2`, `fuq_mul*`, `fuq_tbl*`, `fuq_sa3`, `fuq_gst*`,
`fuq_loc8inc*`. FXU leaf: `xuq_alu_add/or3232/mrg/mask/ins/rol64/caor`,
`xuq_add*`, `xuq_alu_mult*`, `xuq_agen*`. Support: `ibm`, `support`, `clib`,
all of `tri`. Everything else (`fuq.v`, `fuq_dcd/pic/cr2/fpr/scr/eie/eov/sto`,
`xuq.v`/`xuq_alu`/`xuq_dec`/`byp`/`cpl`/`fxu`/`spr`, `iuq_*`, `bxq`, `mmq*`,
`pcq*`, `a2l2_axi`) is ISA/control and moves to the Chisel layer.

## Verified so far (simulation)

- `python3 tools/run.py tb.tb_fumul.fuq_mul` → **PASS** (VUnit, GHDL 7).
  `tb/tb_fumul.vhdl` is the first unit bench through the frozen layer: proves
  `fuq_mul` elaborates, clocks (1-cycle ex1→ex2 latency), and produces a
  carry-save product that reconstructs `a*c + 2^107` (constant Booth sign
  term) **exactly** for the tested domain — zero + 3*5 sanity, 7 domain
  vectors (single-hot + shifted-large operands), 50 randoms (sparse
  multiplier `a`≤16b, dense 54b multiplicand `c`).
  - `fuq_mul` contract: `a_frac(0:52)` Booth-recoded multiplier,
    `c_frac(0:53)` multiplicand; carry-save `sum(1:108)+car(1:108)`, MSB-first
    (index 1 = weight 2^107), `m62` combinational.
  - **Limitation:** dense/large multiplier operands emit per-digit hot_one/
    sign corrections that need the FPU normalize model to fold — a bit-exact
    check there is deferred to formal equivalence or a CPA-level test, not a
    DUT defect.
- `python3 tools/run.py tb.tb_xuagen.xuq_agen` → **PASS**. `xuq_agen` is
  combinational (no clock): `sum_non_erat = (x+y) mod 2^64` **exactly** (no
  constant offset), `sum(0:51) = (x+y)>>12`, `sum_arr_dir*` = word bits 53–57,
  `sum` = `snoop_addr` when `snoop_sel='1'`. Coverage: zero/small/single-hot
  at field boundaries, all-ones, ~50 dense randoms, snoop path.
- Toolchain note: system GHDL 5's mcode crashes on `PIN_BIT_INFORMATION`;
  oss-cad GHDL 7 (LLVM) is required and is ~4s/file — the narrowed `top`
  library keeps first-run compile tractable; later runs are seconds.

### Full-core `a2x_axi` (sim/coco)

- **The entire core elaborates + links in open-EDA**: `sim/coco/a2x_axi` is a
  ~196MB ELF built by oss-cad-suite GHDL 7-LLVM. `ghdl -r --work=work a2x_axi
  --stop-time=N` runs clean standalone (no stimulus → quiescent, as expected).
- Harness `sim/coco/run.sh` = `gen → analyze → elab → sim`:
  - `gen_sim_shadow.py` derives `sim_shadow/{ibm,support,clib,tri}` with
    `pin_bit_information` **attr-specs** stripped (elab bound-check fix) while
    keeping the `pbi_t` type decl. `analyze` MUST use shadow `ibm`/`support`,
    not canonical — otherwise `PIN_BIT_INFORMATION` fires at `ghdl -e/-r`.
  - `analyze` is dependency-ordered + incremental (`.done`): pkg-first libs,
    `tri`/`work` iterate to fixpoint because files instantiate each other.
  - `unimacro_sim/bram_tdp_macro_sim.vhdl` is the behavioral TDP-BRAM arch
    (entity-only mock → real array + INIT preload). WORDS clamps to DEPTH
    (`ramb16_s9_s9`/ierat_cam: `128*256/9=3640 > 2048` → bound-check, fixed).
  - GHDL obsoletion = `.o` mtime ordering: re-analyzing a package/entity
    re-dates it and obsoletes dependents. `ghdl -m ... a2x_axi` re-analyzes the
    whole `work` tree bottom-up and restores order — the recovery tool. The
    `elab` self-heal loop only refreshes `work` units, never packages.
  - cocotb 2.x VPI env: `GPI_USERS=<shared libpython.so>;<cocotb.simulator
    .so>,initialize`, `PYGPI_PYTHON_BIN`, `COCOTB_TEST_MODULES=tb`,
    `COCOTB_TOPLEVEL=a2x_axi`, `TOPLEVEL_LANG=vhdl`, `PYTHONPATH=sim/coco`
    (all set in `run.sh`).
- **Known blocker:** cocotb loads + runs `tb_a2x_axi_reset_and_axi`, prints
  `reset released` at 40ns, then sim-time freezes at 44ns / 0% CPU — the
  `Clock(dut.clk)` value-writes don't generate VHDL events under GHDL-LLVM's
  VPI (design simulates fine standalone). Fix in flight: drive `clk`/`clk2x`
  in a thin VHDL `tb_top` and keep cocotb for AXI only.

## Next (P1+)

- Finish `sim/coco` clock-delivery (VHDL `tb_top` or cocotb workaround) so the
  core advances past reset and issues an AXI fetch; then memory preload +
  magic-address pass/fail per `../a2o/dev/sim/coco`.
- Extend unit benches to `xuq_alu` (registered FXU ALU; bigger — threads,
  bypass, decode) and other `fuq_*`/`xuq_*` leaves (same `tb/` pattern).
