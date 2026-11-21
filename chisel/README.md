# amcore — Amaranth CPU IP Generator

Generates pipeline control + ISA logic around the **frozen A2I datapath
kernels** (`fuq_mul`, `xuq_alu`, `xuq_agen`, …). Pure-Python (Amaranth HDL,
no JVM); emits Verilog that instantiates the golden entities as blackboxes.

> Named `chisel/` from the original plan; the generator is **Amaranth**
> (chosen over Chisel — pure Python, no sbt/JVM, same BlackBox interop).

## Architecture

```
chisel/
├── tools/gen_manifest_kernels.py  # frozen-entity parser → manifest.json
├── kernels/manifest.json          # 7 kernels, 291 ports (dirs/widths/roles)
└── amcore/
    ├── kernel.py                  # Kernel: manifest → Instance blackbox
    ├── pipeline.py                # PipelineSkeleton: N-stage valid/flush
    ├── profiles/
    │   ├── a2i.py                 # in-order: IF→ID→RF→EX→WB + scoreboard
    │   └── a2o.py                 # OoO: disp→rn→rs→iss→ex→cdb→cpl + RS/CDB
    └── emit.py                    # top-level generator CLI
```

## The kernel-wrapping contract

Each frozen entity's `port(...)` is parsed once into `manifest.json`:
`{name, dir, type, lo, hi, width, msb_first, role}` with role ∈
`pervasive`/`control`/`data`.

- **`pervasive`** (`vdd/gnd/clkoff_b/act_dis/delay_lclkr/mpw*_b/sg_1/thold_1/
  nclk/*_si/*_so`) → tied off for `expand_type=1`/`thold=0` in `PERVASIVE_TIE`
  (plain rising-edge regs, no scan). `nclk`/`vdd`/`gnd` handled at a higher level.
- **`control`** (`ex1_act`, `flush`, enables) → `Kernel.c_<name>` Signals the
  pipeline drives (stage-valid → `ex1_act`, etc.). `fpu_enable`-class
  `dc_act` enables are `TIE_HIGH_ENABLES` (tied `1`, not driven).
- **`data`** (operand/result buses) → `Kernel.p_<name>` LSB-first Signals.

**MSB-first boundary:** golden buses are `std_ulogic_vector(0 to N)`, index 0
= MSB. The wrapper exposes a flat N-bit Signal and emits a `[width-1-i]`
bit-swap at the `Instance` port map, so golden index `i` ↔ signal bit
`width-1-i`. Pipelines see normal LSB-first values.

## Profiles (unification point)

`isa` decode is shared; `profiles/*` select control style around the same
kernels:

- **`a2i` in-order** — matches `a2x_axi`. EX stage = `Kernel(fu)`;
  `ex1_act = valid & ~flush & ~stall`; per-dest scoreboard → RAW interlock.
- **`a2o` out-of-order** — adds RS entry (busy/op/operand tags+ready),
  tag wakeup on the CDB broadcast, in-order completion.

A generated core = profile + ISA + kernel set + params (threads, expand_type,
queue sizes). v1 wraps one kernel (`fuq_mul`) end-to-end through each profile
to prove the plumbing before ISA breadth.

## Usage

```sh
pip install amaranth          # 0.5.10
cd chisel
python3 -m amcore.emit --profile a2i --fu fuq_mul -o build/a2i_fuq_mul.v
python3 -m amcore.emit --profile a2o --fu fuq_mul -o build/a2o_fuq_mul.v
# regen manifest after any golden change (frozen → rare):
python3 tools/gen_manifest_kernels.py
```

Emitted `.v` instantiates `fuq_mul` (etc.) by name; the golden VHDL/Verilog
compiles separately and binds at elaboration (same as the `sim/coco` bench).

## Status

- [x] manifest generator (7 kernels, verified vs entities)
- [x] `Kernel` blackbox + MSB-first swap (verified: `fuq_mul` inst correct)
- [x] a2i + a2o skeletons emit with kernel instantiated
- [ ] drive `ex1_act`/operands from a stage payload (not constants)
- [ ] cocotb check vs `tb_fumul` golden vectors through generated wrapper
- [ ] ISA decode tables → control-signal generation
- [ ] operand RF-read muxes + writeback + bypass network
