"""A2I profile — in-order pipeline, matching the frozen a2x_axi datapath.

Stage sequence (v1):
    IF (instr in) -> ID (PPC64 decode) -> RF (FPR read + operand stage)
        -> EX (fuq_mul kernel) -> WB (write FRT + scoreboard clear)

v1 scope: the FP multiply class (fmul/fmsub/fnmadd-family + fcfid) decoded
into the `f_dcd_rf1_*` control contract, operands read from a 64-entry FPR,
multiplied by the golden `fuq_mul`, product written back to FRT. Proves the
full decode -> operand -> kernel -> writeback plumbing before ISA breadth.
"""

from __future__ import annotations

from amaranth import Array, Const, Module, Signal

from ..isa.ppc64 import Decoded, SEL_FCFID, SEL_FMADD_SUB, SEL_FMUL
from ..kernel import Kernel
from ..pipeline import PipelineSkeleton, Stage

STAGES = ["if", "id", "rf", "ex", "wb"]

# fuq_mul field widths (manifest).
A_FRAC_W = 53   # f_fmt_ex1_a_frac  : std_ulogic_vector(0 to 52)
C_FRAC_W = 54   # f_fmt_ex1_c_frac  : std_ulogic_vector(0 to 53)
PROD_W = 108    # f_mul_ex2_sum/car : std_ulogic_vector(1 to 108)
FPR_W = 64      # 64-bit architectural FP register
NFPR = 64       # 32 architected + 32 upper (A2I uses 7-bit FP reg ids)


class InOrderCore(PipelineSkeleton):
    """Minimal in-order core wrapping `fuq_mul`, with decode + FPR.

    External interface (v1): drive `instr` (32b PPC) + `instr_v`; the core
    decodes, reads the FPR, multiplies, and writes FRT back. `wb_*` exposes
    the writeback for a testbench/scoreboard. The FPR is internal (loaded
    via `fpr_we`/`fpr_waddr`/`fpr_wdata` for test vectors or a later LSU).
    """

    PROFILE = "a2i"

    def __init__(self, fu_kernel: str = "fuq_mul", threads: int = 1):
        super().__init__(STAGES)
        self.fu_kernel = fu_kernel
        self.threads = threads

        # ---- upstream interface ------------------------------------------
        self.instr = Signal(32, name="instr")
        self.instr_v = Signal(name="instr_v")

        # ---- FPR (v1 internal; a real LSU/RF stage refines it) -----------
        self.fpr = Array(Signal(FPR_W, name=f"fpr{i}") for i in range(NFPR))
        self.fpr_we = Signal(name="fpr_we")
        self.fpr_waddr = Signal(6, name="fpr_waddr")
        self.fpr_wdata = Signal(FPR_W, name="fpr_wdata")

        # ---- writeback (exposed for TB / scoreboard) ---------------------
        self.wb_addr = Signal(6, name="wb_addr")
        self.wb_data = Signal(FPR_W, name="wb_data")
        self.wb_valid = Signal(name="wb_valid")

        # ---- scoreboard: 1 busy bit per FPR ------------------------------
        self.sb_busy = Signal(NFPR, name="sb_busy")

        # ex-stage operand registers (kept out of generic payload so the
        # skeleton's forward-register doesn't double-drive them)
        self.ex_op_a = Signal(FPR_W, name="ex_op_a")
        self.ex_op_b = Signal(FPR_W, name="ex_op_b")
        self.ex_op_c = Signal(FPR_W, name="ex_op_c")

        # decoded fields carried id -> rf -> ex (operand + control)
        self._dcd = Decoded()

    def ports(self):
        from amaranth.hdl import IOPort
        return [
            IOPort(32, name="instr"), IOPort(1, name="instr_v"),
            IOPort(1, name="fpr_we"), IOPort(6, name="fpr_waddr"),
            IOPort(FPR_W, name="fpr_wdata"),
            IOPort(6, name="wb_addr"), IOPort(FPR_W, name="wb_data"),
            IOPort(1, name="wb_valid"),
            IOPort(1, name="stall"), IOPort(1, name="flush_all"),
        ]

    # --- per-stage wiring -------------------------------------------------
    def wire_stage(self, m: Module, i: int, st: Stage, prev):
        # NOTE: populate st.payload + st.override FIRST, then call
        # super().wire_stage which actually emits the registers — calling it
        # first would register an empty payload.
        d = self._dcd

        if st.name == "if":
            # capture the instruction word; `id` decodes it combinationally.
            st.add("instr", 32)
            st.override["instr"] = self.instr

        elif st.name == "id":
            # decode runs comb on the if-staged instruction -> control bundle
            st.add("instr", 32)
            self._dcd.emit(m, prev.payload["instr"])
            for nm in ("valid", "is_mul", "math_b", "sub_op_b", "inv_sign_b",
                       "from_int_b", "frsp_b", "rt", "ra", "rb", "rc",
                       "ra_v", "rb_v", "rc_v", "rt_v"):
                sig = getattr(self._dcd, nm)
                st.add(nm, sig.shape().width)
                st.override[nm] = sig
            # gate stage-valid on a successful decode so invalid ops die
            st.override["valid"] = self._dcd.valid & prev.valid
            # RAW interlock (A2I bypsel drives this): if any valid source reg
            # is scoreboard-busy, hold this instruction until the producer's
            # writeback clears the busy bit. Stall this stage + upstream.
            busy = Signal(name="raw_hazard")
            m.d.comb += busy.eq(
                (self._dcd.ra_v & self.sb_busy.bit_select(self._dcd.ra, 1)) |
                (self._dcd.rb_v & self.sb_busy.bit_select(self._dcd.rb, 1)) |
                (self._dcd.rc_v & self.sb_busy.bit_select(self._dcd.rc, 1)))
            st.stall = busy
            # mark the destination busy as the op enters decode (in-order
            # single-issue means one producer in flight per reg is enough)
            with m.If(prev.valid & self._dcd.valid & self._dcd.rt_v & ~busy):
                m.d.sync += self.sb_busy.bit_select(self._dcd.rt, 1).eq(1)

        elif st.name == "rf":
            # carry control forward; read FPR operands from decoded addresses.
            # rf is a 7b reg id -> narrow to the 6b FPR index.
            for nm in ("valid", "is_mul", "math_b", "sub_op_b", "inv_sign_b",
                       "from_int_b", "frsp_b", "rt", "ra", "rb", "rc",
                       "ra_v", "rb_v", "rc_v", "rt_v"):
                sig = prev.payload[nm]
                st.add(nm, sig.shape().width)
            # operand registers (read comb at rf, registered into ex below)
            st.add("op_a", FPR_W); st.add("op_b", FPR_W); st.add("op_c", FPR_W)
            # reg ids are 7b; FPR array is 64-deep -> index on low 6 bits
            st.override["op_a"] = self.fpr[prev.payload["ra"].bit_select(0, 6)]
            st.override["op_b"] = self.fpr[prev.payload["rb"].bit_select(0, 6)]
            st.override["op_c"] = self.fpr[prev.payload["rc"].bit_select(0, 6)]

        elif st.name == "ex":
            for nm in ("valid", "is_mul", "rt", "rt_v"):
                sig = prev.payload[nm]
                st.add(nm, sig.shape().width)
            # register the operands into EX (the f_fmt_ex1_* contract)
            m.d.sync += self.ex_op_a.eq(prev.payload["op_a"])
            m.d.sync += self.ex_op_b.eq(prev.payload["op_b"])
            m.d.sync += self.ex_op_c.eq(prev.payload["op_c"])
            self._build_ex(m, st, prev)

        elif st.name == "wb":
            st.add("rt", 6); st.add("rt_v", 1); st.add("result", FPR_W)
            self._build_wb(m, st, prev)
        super().wire_stage(m, i, st, prev)

    # --- EX: the fuq_mul kernel -------------------------------------------
    def _build_ex(self, m, st, prev):
        self._ex = Kernel(self.fu_kernel)
        m.submodules.ex_fu = k = self._ex

        act = getattr(k, "c_ex1_act", None)
        if act is not None:
            m.d.comb += act.eq(st.valid & ~st.flush & ~self.stall)
        fl = getattr(k, "c_flush", None)
        if fl is not None:
            m.d.comb += fl.eq(st.flush | self.flush_all)

        # operand formatting per decode: FPR value -> fuq_mul frac fields.
        # v1 truncates to field width (exponents/format-normalisation is the
        # datapath-correctness follow-up); fcfid routes the integer into C.
        a = getattr(k, "p_f_fmt_ex1_a_frac", None)
        c = getattr(k, "p_f_fmt_ex1_c_frac", None)
        is_fcfid = prev.payload["is_mul"] == Const(SEL_FCFID, 2)
        if a is not None:
            m.d.comb += a.eq(self.ex_op_a[:A_FRAC_W])
        if c is not None:
            m.d.comb += c.eq(self.ex_op_c[:C_FRAC_W])

        # carry-save product -> a single wb value (v1: sum+car folded by a
        # placeholder CPA; the real normalize/round is a follow-up).
        s = getattr(k, "p_f_mul_ex2_sum", None)
        r = getattr(k, "p_f_mul_ex2_car", None)
        self._ex_result = Signal(FPR_W, name="ex_result")
        if s is not None and r is not None:
            m.d.comb += self._ex_result.eq(s[:FPR_W] + r[:FPR_W])

    # --- WB: write FRT + clear scoreboard ---------------------------------
    def _build_wb(self, m, st, prev):
        s = getattr(self._ex, "p_f_mul_ex2_sum", None)
        r = getattr(self._ex, "p_f_mul_ex2_car", None)
        # register the EX result into wb
        rt = st.payload["rt"].bit_select(0, 6)
        st.override["result"] = self._ex_result
        st.override["rt"] = prev.payload["rt"].bit_select(0, 6)
        st.override["rt_v"] = prev.payload["rt_v"]
        m.d.comb += self.wb_addr.eq(rt)
        m.d.comb += self.wb_data.eq(st.payload["result"])
        m.d.comb += self.wb_valid.eq(st.valid & st.payload["rt_v"])
        # architected writeback into the FPR + scoreboard clear (always-ready
        # write port in v1; a real RF may add backpressure later)
        with m.If(st.valid & st.payload["rt_v"]):
            m.d.sync += self.fpr[rt].eq(st.payload["result"])
            m.d.sync += self.sb_busy.bit_select(rt, 1).eq(0)
        # external FPR preload (test vectors / LSU)
        with m.If(self.fpr_we):
            m.d.sync += self.fpr[self.fpr_waddr].eq(self.fpr_wdata)
            m.d.sync += self.sb_busy.bit_select(self.fpr_waddr, 1).eq(0)
