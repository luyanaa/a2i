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
XOW = slice(1, 11)    # XO (full 10b)    instr[21:30] -> Am 1..10 ; pri-31 ops
XO9 = slice(1, 10)    # XO (mid 9b)      instr[22:30] -> Am 1..9  ; mul ops
                      # golden xuq_dec_b decodes mul/div on instr[22:30]
                      # (9 bits, ignoring instr[21]=OE) -> match XO9.
RCBIT = 0             # Rc               instr[31]    -> Am 0

OP_FP = 63            # scalar FP arithmetic + moves
OP_XO = 31            # GPR arithmetic/logical (add, subf, and, or, xor, ...)
OP_ADDI = 14          # addi   RT <- RA + SIMM
OP_ADDIS = 15         # addis  RT <- RA + (SIMM << 16)
# D-form loads/stores: EA = RA + SIMM (displacement). Data movement, not
# arithmetic — goes to the AGEN to form the effective address.
OP_LWZ = 32           # lwz  RT <- mem[RA+SIMM]
OP_STW = 36           # stw  mem[RA+SIMM] <- RT(store data in RT field slot)
OP_LD = 58            # ld   RT <- mem[RA+DS]  (DS-form, low 2b = 0)
OP_STD = 62           # std  mem[RA+DS] <- RT
# immediate logical ops (D-form): RT <- RA <fcn> UIMM (zero-extended 16b)
OP_ANDI = 28          # andi.  (Rc=1 forced)
OP_ORI = 24           # ori
OP_XORI = 26          # xori

# XO codes (low 5b, instr[26:30]) — shared field across FP and GPR ops.
# FP multiply class
XO_FMUL = 25
XO_FMULS = 18
XO_FMSUB = 28
XO_FMSUBS = 20
XO_FNMSUB = 30
XO_FNMSUBS = 22
XO_FCFID = 846 & 0b11111    # =14 ; fcfid's full XO is instr[21:31]
XO_FCFIDS = 798 & 0b11111   # =30 ; v1 matches low 5b, tighten later
# GPR arithmetic (op 31 + XO). Values are the low 5b of the 10-bit XO
# instr[21:30]; v1 matches low 5b (add/subf/cmp low nibbles are distinct).
XO_ADD = 266 & 0b11111      # =10   add   RT <- RA + RB
XO_SUBF = 40  & 0b11111     # =8    subf  RT <- RB - RA
XO_CMP = 0                  #       cmp   RA vs RB (CR write, no RT)
# GPR logical ops — full 10-bit XO instr[21:30] (low-5b collides: or=444 and
# and=28 share low5b=28). Use XOW-wide values for these.
XO_AND = 28
XO_OR = 444
XOX = XOXOR = 316           # (avoid clashing with XO const name)
XO_XOR = 316
XO_NAND = 476
XO_NOR = 124
XO_ANDC = 60
XO_EQV = 568
# GPR multiply (pri 31 + XO). xuq_alu_mult drives dec_alu_rf1_mul_*:
#   ret  = return HIGH word/dword (mulhw/mulhwu/mulhd/mulhdu)
#   size = 1 for 64x64 (mulld/mulli/mulhd/mulhdu), 0 for 32x32 (mullw/mulhw)
#   imm  = 1 for mulli (multiplier is the 16b SE immediate)
#   sign = 1 signed (NOT mulhwu/mulhdu)
# Encodings from xuq_dec_b.vhdl:1791-1797: the golden matches instr[22:30],
# a 9-bit XO field (drops instr[21]=OE). Match it via the XO9 slice.
XO_MULLW = 0b011101011    # mullw  =235  low-half 32x32 signed
XO_MULHW = 0b001001011    # mulhw  =75   high-half 32x32 signed
XO_MULHWU = 0b000001011   # mulhwu =11   high-half 32x32 unsigned
XO_MULLD = 0b011101001    # mulld  =233  low-half 64x64 signed
XO_MULHD = 0b001001001    # mulhd  =73   high-half 64x64 signed
XO_MULHDU = 0b000001001   # mulhdu =9    high-half 64x64 unsigned
# mulli is D-form (own primary opcode 7, not an XO op)
OP_MULLI = 7
# GPR divide (pri 31 + 9-bit instr[22:30] XO, same field the mul ops use)
XO_DIVW  = 0b111101011   # divw  =491 32/32 signed
XO_DIVWU = 0b111001011   # divwu =459 32/32 unsigned
XO_DIVD  = 0b111101001   # divd  =489 64/64 signed
XO_DIVDU = 0b111001001   # divdu =457 64/64 unsigned
XO_DIVWE = 0b110101011   # divwe =427 extd 32/32 signed
XO_DIVDE = 0b011001001   # divde =201 extd 64/64 signed
# marker: an XO value OR'd with WIDE matches the full 10-bit XOW field
# (instr[1:11]) instead of the low 5 bits — needed for GPR ops where several
# share the same low-5b tail (e.g. and=28 vs or=444 -> both low5b=28).
WIDE = 0x10000

# is_mul operation selector -> operand source / formatting in the pipeline.
SEL_FMUL = 0        # A * C
SEL_FMADD_SUB = 1   # A * C (+/-) B
SEL_FCFID = 2       # int64 -> fraction

# fu_sel: which functional unit executes the op.
FU_FPU = 0          # fuq_*  (FP datapath)
FU_FXU_ADD = 1      # xuq_alu_add (GPR add/sub/cmp adder)
FU_AGEN = 2         # xuq_agen    (load/store effective address)
FU_FXU_LOG = 3      # xuq_alu     (GPR logical ops via the logic unit)
FU_FXU_MUL = 4      # xuq_alu     (GPR multiply via the Booth unit, 5-cycle)
FU_FXU_DIV = 5      # xuq_alu     (GPR divide, iterative ~33/65/129 cycles)

# GPR arithmetic op-select (drives dec_alu_rf1_* controls on xuq_alu_add).
ALUOP_ADD = 0       # rs0 + rs1          (add / addi / addis)
ALUOP_SUBF = 1      # rs1 - rs0          (subf)
ALUOP_CMP = 2       # compare (sets ex2_cr_recform, no GPR write)

# AGEN op-select (drives the load/store effective-address path).
AGEN_LOAD = 0       # EA = RA + SIMM, result is an address for a LOAD
AGEN_STORE = 1      # EA = RA + SIMM, address for a STORE (RT is data source)

# xuq_alu logic-unit function select: log_fcn(0..3) is a 2-input truth table
# (MSB-first) gating minterms ~a~b,~a·b,a·~b,a·b -> out = OR of enabled terms.
LOG_AND = 0b0001    # a & b        (minterm3)
LOG_OR = 0b0111     # a | b        (m1+m2+m3)
LOG_XOR = 0b0110    # a ^ b        (m1+m2)
LOG_NAND = 0b1110   # ~(a & b)     (m0+m1+m2)
LOG_NOR = 0b1000    # ~(a | b)     (m0)
LOG_ANDC = 0b0010   # a & ~b       (m2)
LOG_EQV = 0b1001    # a == b       (m0+m3)

# Decode table rows:
#   (pri, xo_or_None, fu_sel, is_mul, math_b, sub_op, inv_sign, from_int,
#    frsp, alu_op, ra_v, rb_v, rc_v, rt_v, uses_simm, log_fcn,
#    mul_ret, mul_size, mul_imm, mul_sign,
#    div_sign, div_size, div_extd, div_ctr)
# xo_or_None=None matches any XO (immediate-form ops); else XO match. An XO
# OR'd with WIDE matches the full 10-bit field (pri-31 ops collide on low5b);
# an XO OR'd with WIDE9 matches the 9-bit instr[22:30] field the golden uses
# for mul/div (it drops instr[21]=OE).
WIDE9 = 0x20000
_TABLE = [
    # ---- FP multiply family (pri 63) ----
    (OP_FP, XO_FMUL,    FU_FPU, SEL_FMUL,      1,0,0,0,0, 0, 1,0,1,1, 0, 0, 0,0,0,0, 0,0,0,0),
    (OP_FP, XO_FMULS,   FU_FPU, SEL_FMUL,      1,0,0,0,1, 0, 1,0,1,1, 0, 0, 0,0,0,0, 0,0,0,0),
    (OP_FP, XO_FMSUB,   FU_FPU, SEL_FMADD_SUB, 1,1,0,0,0, 0, 1,1,1,1, 0, 0, 0,0,0,0, 0,0,0,0),
    (OP_FP, XO_FMSUBS,  FU_FPU, SEL_FMADD_SUB, 1,1,0,0,1, 0, 1,1,1,1, 0, 0, 0,0,0,0, 0,0,0,0),
    (OP_FP, XO_FNMSUB,  FU_FPU, SEL_FMADD_SUB, 1,1,1,0,0, 0, 1,1,1,1, 0, 0, 0,0,0,0, 0,0,0,0),
    (OP_FP, XO_FNMSUBS, FU_FPU, SEL_FMADD_SUB, 1,1,1,0,1, 0, 1,1,1,1, 0, 0, 0,0,0,0, 0,0,0,0),
    (OP_FP, XO_FCFID,   FU_FPU, SEL_FCFID,     0,0,0,1,0, 0, 0,1,0,1, 0, 0, 0,0,0,0, 0,0,0,0),
    (OP_FP, XO_FCFIDS,  FU_FPU, SEL_FCFID,     0,0,0,1,1, 0, 0,1,0,1, 0, 0, 0,0,0,0, 0,0,0,0),
    # ---- GPR arithmetic (pri 31 + XO low5b) ----
    (OP_XO, XO_ADD,     FU_FXU_ADD, 0, 0,0,0,0,0, ALUOP_ADD,  1,1,0,1, 0, 0, 0,0,0,0, 0,0,0,0),
    (OP_XO, XO_SUBF,    FU_FXU_ADD, 0, 0,0,0,0,0, ALUOP_SUBF, 1,1,0,1, 0, 0, 0,0,0,0, 0,0,0,0),
    (OP_XO, XO_CMP,     FU_FXU_ADD, 0, 0,0,0,0,0, ALUOP_CMP,  1,1,0,0, 0, 0, 0,0,0,0, 0,0,0,0),
    # ---- immediate add (own primary) ----
    (OP_ADDI, None,     FU_FXU_ADD, 0, 0,0,0,0,0, ALUOP_ADD,  1,0,0,1, 1, 0, 0,0,0,0, 0,0,0,0),
    (OP_ADDIS, None,    FU_FXU_ADD, 0, 0,0,0,0,0, ALUOP_ADD,  1,0,0,1, 1, 0, 0,0,0,0, 0,0,0,0),
    # ---- D-form load/store -> AGEN for the effective address ----
    #   load : reads RA (+SIMM), writes RT with the loaded data -> rt_v=1
    #   store: reads RA (+SIMM) AND RT (store data) -> rt_v=0, rt used as src
    (OP_LWZ, None,      FU_AGEN, 0, 0,0,0,0,0, AGEN_LOAD,  1,0,0,1, 1, 0, 0,0,0,0, 0,0,0,0),
    (OP_STW, None,      FU_AGEN, 0, 0,0,0,0,0, AGEN_STORE, 1,0,0,0, 1, 0, 0,0,0,0, 0,0,0,0),
    (OP_LD,  None,      FU_AGEN, 0, 0,0,0,0,0, AGEN_LOAD,  1,0,0,1, 1, 0, 0,0,0,0, 0,0,0,0),
    (OP_STD, None,      FU_AGEN, 0, 0,0,0,0,0, AGEN_STORE, 1,0,0,0, 1, 0, 0,0,0,0, 0,0,0,0),
    # ---- GPR logicals (pri 31 + full-10b XO; also immediate D-form) ----
    #   rt <- ra <fcn> rb   (or ra <fcn> UIMM for the D-form ops)
    (OP_XO, XO_AND|WIDE,  FU_FXU_LOG, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, LOG_AND,  0,0,0,0, 0,0,0,0),
    (OP_XO, XO_OR |WIDE,  FU_FXU_LOG, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, LOG_OR,   0,0,0,0, 0,0,0,0),
    (OP_XO, XO_XOR|WIDE,  FU_FXU_LOG, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, LOG_XOR,  0,0,0,0, 0,0,0,0),
    (OP_XO, XO_NAND|WIDE, FU_FXU_LOG, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, LOG_NAND, 0,0,0,0, 0,0,0,0),
    (OP_XO, XO_NOR |WIDE, FU_FXU_LOG, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, LOG_NOR,  0,0,0,0, 0,0,0,0),
    (OP_XO, XO_ANDC|WIDE, FU_FXU_LOG, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, LOG_ANDC, 0,0,0,0, 0,0,0,0),
    (OP_XO, XO_EQV |WIDE, FU_FXU_LOG, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, LOG_EQV,  0,0,0,0, 0,0,0,0),
    (OP_ANDI, None,       FU_FXU_LOG, 0, 0,0,0,0,0, 0, 1,0,0,1, 1, LOG_AND,  0,0,0,0, 0,0,0,0),
    (OP_ORI,  None,       FU_FXU_LOG, 0, 0,0,0,0,0, 0, 1,0,0,1, 1, LOG_OR,   0,0,0,0, 0,0,0,0),
    (OP_XORI, None,       FU_FXU_LOG, 0, 0,0,0,0,0, 0, 1,0,0,1, 1, LOG_XOR,  0,0,0,0, 0,0,0,0),
    # ---- GPR multiply (pri 31 + 9-bit instr[22:30] XO; own Booth FU) ----
    #   ret=high half, size=64x64, imm=immediate, sign=signed
    (OP_XO, XO_MULLW|WIDE9, FU_FXU_MUL, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, 0, 0,0,0,1, 0,0,0,0),
    (OP_XO, XO_MULHW|WIDE9, FU_FXU_MUL, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, 0, 1,0,0,1, 0,0,0,0),
    (OP_XO, XO_MULHWU|WIDE9,FU_FXU_MUL, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, 0, 1,0,0,0, 0,0,0,0),
    (OP_XO, XO_MULLD|WIDE9, FU_FXU_MUL, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, 0, 0,1,0,1, 0,0,0,0),
    (OP_XO, XO_MULHD|WIDE9, FU_FXU_MUL, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, 0, 1,1,0,1, 0,0,0,0),
    (OP_XO, XO_MULHDU|WIDE9,FU_FXU_MUL, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, 0, 1,1,0,0, 0,0,0,0),
    (OP_MULLI, None,        FU_FXU_MUL, 0, 0,0,0,0,0, 0, 1,0,0,1, 1, 0, 0,1,1,1, 0,0,0,0),
    # ---- GPR divide (pri 31 + 9-bit instr[22:30] XO; iterative xuq_alu_div) --
    #   sign/size/extd from xuq_dec_b; div_ctr = recirc_ctr_init (TBL_RF0_DEC):
    #   divw/wu=33  divd/du/divwe/weu=65  divde/deu=129
    (OP_XO, XO_DIVW|WIDE9,  FU_FXU_DIV, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, 0, 0,0,0,0, 1,0,0,33),
    (OP_XO, XO_DIVWU|WIDE9, FU_FXU_DIV, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, 0, 0,0,0,0, 0,0,0,33),
    (OP_XO, XO_DIVD|WIDE9,  FU_FXU_DIV, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, 0, 0,0,0,0, 1,1,0,65),
    (OP_XO, XO_DIVDU|WIDE9, FU_FXU_DIV, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, 0, 0,0,0,0, 0,1,0,65),
    (OP_XO, XO_DIVWE|WIDE9, FU_FXU_DIV, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, 0, 0,0,0,0, 1,0,1,65),
    (OP_XO, XO_DIVDE|WIDE9, FU_FXU_DIV, 0, 0,0,0,0,0, 0, 1,1,0,1, 0, 0, 0,0,0,0, 1,1,1,129),
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
        self.fu_sel = Signal(3, name="dcd_fu_sel")
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
        # GPR/immediate extras
        self.alu_op = Signal(2, name="dcd_alu_op")     # ALUOP_* for FU_FXU_ADD
        self.uses_simm = Signal(name="dcd_uses_simm")  # operand B <- SIMM not RB
        self.simm = Signal(16, name="dcd_simm")         # instr[16:31] immediate
        self.log_fcn = Signal(4, name="dcd_log_fcn")   # truth-table sel (FU_FXU_LOG)
        # mul controls (FU_FXU_MUL): dec_alu_rf1_mul_{ret,size,imm,sign}
        self.mul_ret = Signal(name="dcd_mul_ret")   # return high word/dword
        self.mul_size = Signal(name="dcd_mul_size") # 0=32x32, 1=64x64
        self.mul_imm = Signal(name="dcd_mul_imm")   # 1 = 16b immediate multiplier
        self.mul_sign = Signal(name="dcd_mul_sign") # 1 = signed
        # div controls (FU_FXU_DIV): dec_alu_rf1_div_{sign,size,extd} + div_ctr
        self.div_sign = Signal(name="dcd_div_sign") # 1 = signed
        self.div_size = Signal(name="dcd_div_size") # 0=32b(divw) 1=64b(divd)
        self.div_extd = Signal(name="dcd_div_extd") # 1 = extended dividend
        self.div_ctr = Signal(8, name="dcd_div_ctr") # recirc iteration count

    def emit(self, m: Module, instr: Signal, domain: str = "comb"):
        """Drive all control signals combinationally from `instr`."""
        d = getattr(m.d, domain)
        pri = instr[PRI]
        xof = instr[XO]   # XO FIELD slice (was `xo`; renamed so the table
                          # loop var `xo` can't shadow it into a python int)
        # register fields + immediate are unconditional (harmless if invalid)
        d += [
            self.rt.eq(instr[RT]), self.ra.eq(instr[RA]),
            self.rb.eq(instr[RB]), self.rc.eq(instr[RC]),
            self.simm.eq(instr[0:16]),    # SIMM = IBM instr[16:31] -> Am 0..15
            # defaults: unknown op -> invalid, nothing sourced/written
            self.valid.eq(0), self.fu_sel.eq(0), self.is_mul.eq(SEL_FMUL),
            self.math_b.eq(0), self.sub_op_b.eq(0), self.inv_sign_b.eq(0),
            self.from_int_b.eq(0), self.frsp_b.eq(0),
            self.ra_v.eq(0), self.rb_v.eq(0), self.rc_v.eq(0),
            self.rt_v.eq(0), self.alu_op.eq(ALUOP_ADD), self.uses_simm.eq(0),
            self.log_fcn.eq(0),
            self.mul_ret.eq(0), self.mul_size.eq(0), self.mul_imm.eq(0),
            self.mul_sign.eq(0),
            self.div_sign.eq(0), self.div_size.eq(0), self.div_extd.eq(0),
            self.div_ctr.eq(0),
        ]
        # Two-level decode: primary opcode, then XO. A row with xo=None matches
        # its primary regardless of XO; an xo OR'd with WIDE matches the full
        # 10-bit XOW field, WIDE9 matches the 9-bit instr[22:30] mul field,
        # else the low-5b XO.
        xowf = instr[XOW]
        xo9f = instr[XO9]
        first_p = True
        for pri_op in {row[0] for row in _TABLE}:
            ctx_p = m.If if first_p else m.Elif
            first_p = False
            with ctx_p(pri == Const(pri_op, 6)):
                first_x = True
                for row in _TABLE:
                    if row[0] != pri_op:
                        continue
                    (p2, xo, fu, is_mul, math, sub, inv, fi, frsp,
                     aluop, av, bv, cv, tv, usi, lfcn,
                     mret, msize, mimm, msign,
                     dsign, dsize, dextd, dctr) = row
                    if xo is None:
                        cond = Const(1)
                    elif xo & WIDE9:
                        cond = xo9f == Const(xo & ~WIDE9, 9)
                    elif xo & WIDE:
                        cond = xowf == Const(xo & ~WIDE, 10)
                    else:
                        cond = xof == Const(xo, 5)
                    if first_x:
                        ctx_x = m.If(cond); first_x = False
                    else:
                        ctx_x = m.Elif(cond)
                    with ctx_x:
                        d += [
                            self.valid.eq(1), self.fu_sel.eq(fu),
                            self.is_mul.eq(is_mul), self.math_b.eq(math),
                            self.sub_op_b.eq(sub), self.inv_sign_b.eq(inv),
                            self.from_int_b.eq(fi), self.frsp_b.eq(frsp),
                            self.alu_op.eq(aluop),
                            self.ra_v.eq(av), self.rb_v.eq(bv),
                            self.rc_v.eq(cv), self.rt_v.eq(tv),
                            self.uses_simm.eq(usi), self.log_fcn.eq(lfcn),
                            self.mul_ret.eq(mret), self.mul_size.eq(msize),
                            self.mul_imm.eq(mimm), self.mul_sign.eq(msign),
                            self.div_sign.eq(dsign), self.div_size.eq(dsize),
                            self.div_extd.eq(dextd), self.div_ctr.eq(dctr),
                        ]
        return self


def decode(instr: Signal) -> "Decoded":
    """Convenience for callers that want the bundle without a Module yet —
    you still must call `d.emit(m, instr)` inside elaborate()."""
    return Decoded()
