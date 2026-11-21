"""PPC64 (PowerISA 2.06) decode — v1, FP multiply-class + fcfid.

Emits the `f_dcd_rf1_*`-class control bundle the golden `fuq` datapath
consumes, driven from a compact table so adding an instruction = one row,
not new RTL. Instruction word uses PowerISA big-endian numbering (MSB-first,
matching the golden `std_ulogic_vector(0 to 31)`): primary opcode
instr[0:6], RT/FRT instr[6:11], RA instr[11:16], RB instr[16:21],
RC instr[21:26], XO instr[26:31], Rc instr[31].

v1 coverage — the floating-point multiply family that drives `fuq_mul`:
    fmul / fmuls        (XO 25 / 18)                A*C product
    fmsub / fmsubs      (XO 28 / 20)                A*C - B   (sub_op)
    fnmsub / fnmsubs    (XO 30 / 22)                -(A*C)+B  (sub+inv)
    fcfid / fcfids      (XO 846 / 798 low5b)        int64 -> double frac
Everything else decodes to valid=0 (the table is the extension point).
GPR arithmetic (add/sub/mullw) routes to `xuq_alu`/`xuq_alu_add` in a later
lane — v1 proves the decode->kernel contract on the FP path.

Usage inside elaborate():
    d = Decoded()
    m.submodules.dcd = d         # or just call d.emit(m) for comb logic
    d.emit(m, instr_signal)      # drives all control signals from instr
"""

from __future__ import annotations

from amaranth import Const, Module, Signal

# ---- PowerISA field slices (IBM MSB-first -> Amaranth [lo:hi]) ------------
# IBM numbers bits MSB=0 .. LSB=31; instr[a:b] is the INCLUSIVE bit range.
# An Amaranth Signal index j is weight 2^j (LSB-first), so IBM bit b maps to
# Amaranth bit 31-b. Field instr[a:b] -> Amaranth bits (31-b)..(31-a), i.e.
# slice(31-b, 32-a). Verified: PRI instr[0:5] -> Am [26:32).
PRI = slice(26, 32)   # primary opcode   instr[0:5]   -> Am 26..31
RT = slice(21, 26)    # RT / FRT         instr[6:10]  -> Am 21..25
RA = slice(16, 21)    # RA / FRA         instr[11:15] -> Am 16..20
RB = slice(11, 16)    # RB / FRB         instr[16:20] -> Am 11..15
RC = slice(6, 11)     # RC / FRC         instr[21:25] -> Am 6..10
XO = slice(1, 6)      # XO (low 5b)      instr[26:30] -> Am 1..5
RCBIT = 0             # Rc               instr[31]    -> Am 0

OP_FP = 63            # scalar FP arithmetic + moves

# XO codes (low 5b, instr[26:31]) for the FP-multiply class in v1.
XO_FMUL = 25
XO_FMULS = 18
XO_FMSUB = 28
XO_FMSUBS = 20
XO_FNMSUB = 30
XO_FNMSUBS = 22
XO_FCFID = 846 & 0b11111    # =14 ; fcfid's full XO is instr[21:31]
XO_FCFIDS = 798 & 0b11111   # =30 ; v1 matches low 5b, tighten later

# is_mul operation selector -> operand source / formatting in the pipeline.
SEL_FMUL = 0        # A * C
SEL_FMADD_SUB = 1   # A * C (+/-) B
SEL_FCFID = 2       # int64 -> fraction

# (xo, is_mul, math_b, sub_op, inv_sign, from_int, frsp, ra_v, rb_v, rc_v, rt_v)
_TABLE = [
    (XO_FMUL,    SEL_FMUL,      1, 0, 0, 0, 0,  1, 0, 1, 1),
    (XO_FMULS,   SEL_FMUL,      1, 0, 0, 0, 1,  1, 0, 1, 1),
    (XO_FMSUB,   SEL_FMADD_SUB, 1, 1, 0, 0, 0,  1, 1, 1, 1),
    (XO_FMSUBS,  SEL_FMADD_SUB, 1, 1, 0, 0, 1,  1, 1, 1, 1),
    (XO_FNMSUB,  SEL_FMADD_SUB, 1, 1, 1, 0, 0,  1, 1, 1, 1),
    (XO_FNMSUBS, SEL_FMADD_SUB, 1, 1, 1, 0, 1,  1, 1, 1, 1),
    (XO_FCFID,   SEL_FCFID,     0, 0, 0, 1, 0,  0, 1, 0, 1),
    (XO_FCFIDS,  SEL_FCFID,     0, 0, 0, 1, 1,  0, 1, 0, 1),
]


class Decoded:
    """The per-instruction control bundle (mirrors `f_dcd_rf1_*`).

    Signals are undriven until `emit(m, instr)` is called inside an
    elaborate() — Amaranth control-flow (m.If) needs an active Module.
    `valid=0` marks an unimplemented opcode; `*_v` gate operand register
    reads / ready-bits; `rt_v` gates writeback + scoreboard.
    """

    def __init__(self):
        self.valid = Signal(name="dcd_valid")
        self.fu_sel = Signal(2, name="dcd_fu_sel")
        self.is_mul = Signal(2, name="dcd_is_mul")
        self.math_b = Signal(name="dcd_math_b")
        self.sub_op_b = Signal(name="dcd_sub_op_b")
        self.inv_sign_b = Signal(name="dcd_inv_sign_b")
        self.from_int_b = Signal(name="dcd_from_int_b")
        self.frsp_b = Signal(name="dcd_frsp_b")
        self.rt = Signal(7, name="dcd_rt")
        self.ra = Signal(7, name="dcd_ra")
        self.rb = Signal(7, name="dcd_rb")
        self.rc = Signal(7, name="dcd_rc")
        self.ra_v = Signal(name="dcd_ra_v")
        self.rb_v = Signal(name="dcd_rb_v")
        self.rc_v = Signal(name="dcd_rc_v")
        self.rt_v = Signal(name="dcd_rt_v")

    def emit(self, m: Module, instr: Signal, domain: str = "comb"):
        """Drive all control signals combinationally from `instr`."""
        d = getattr(m.d, domain)
        pri = instr[PRI]
        xo = instr[XO]
        # register fields are unconditional (harmless when invalid)
        d += [
            self.rt.eq(instr[RT]), self.ra.eq(instr[RA]),
            self.rb.eq(instr[RB]), self.rc.eq(instr[RC]),
            # defaults: unknown op -> invalid, nothing sourced/written
            self.valid.eq(0), self.fu_sel.eq(0), self.is_mul.eq(SEL_FMUL),
            self.math_b.eq(0), self.sub_op_b.eq(0), self.inv_sign_b.eq(0),
            self.from_int_b.eq(0), self.frsp_b.eq(0),
            self.ra_v.eq(0), self.rb_v.eq(0), self.rc_v.eq(0),
            self.rt_v.eq(0),
        ]
        with m.If(pri == Const(OP_FP, 6)):
            first = True
            for (xo, is_mul, math, sub, inv, fi, frsp,
                 av, bv, cv, tv) in _TABLE:
                ctx = m.If if first else m.Elif
                first = False
                with ctx(xo == Const(xo, 5)):  # noqa: F821 xo==instr[XO] match
                    d += [
                        self.valid.eq(1), self.is_mul.eq(is_mul),
                        self.math_b.eq(math), self.sub_op_b.eq(sub),
                        self.inv_sign_b.eq(inv), self.from_int_b.eq(fi),
                        self.frsp_b.eq(frsp),
                        self.ra_v.eq(av), self.rb_v.eq(bv),
                        self.rc_v.eq(cv), self.rt_v.eq(tv),
                    ]
        return self


def decode(instr: Signal) -> "Decoded":
    """Convenience for callers that want the bundle without a Module yet —
    you still must call `d.emit(m, instr)` inside elaborate()."""
    return Decoded()
