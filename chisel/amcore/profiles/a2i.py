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

from amaranth import Array, Cat, Const, Module, Mux, Signal

from ..isa.ppc64 import (ALUOP_ADD, ALUOP_CMP, ALUOP_SUBF, Decoded,
                         FU_FPU, FU_FXU_ADD, FU_AGEN,
                         SEL_FCFID, SEL_FMADD_SUB, SEL_FMUL)
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
        # EX combinational result — created here so rf's forward can read it
        # before _build_ex assigns it during the ex stage's wire_stage.
        self._ex_result = Signal(FPR_W, name="ex_result")
        # Producer-tracking signals for the bypsel forward: the ex/wb stages
        # assign these so rf (which elaborates earlier) can compare a source
        # reg against the in-flight producer's destination + grab its result.
        self.prod_ex_rt = Signal(6, name="prod_ex_rt")
        self.prod_ex_rtv = Signal(name="prod_ex_rtv")
        self.prod_ex_res = Signal(FPR_W, name="prod_ex_res")
        self.prod_wb_rt = Signal(6, name="prod_wb_rt")
        self.prod_wb_rtv = Signal(name="prod_wb_rtv")
        self.prod_wb_res = Signal(FPR_W, name="prod_wb_res")

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
                       "from_int_b", "frsp_b", "fu_sel", "alu_op", "uses_simm",
                       "simm", "rt", "ra", "rb", "rc",
                       "ra_v", "rb_v", "rc_v", "rt_v"):
                sig = getattr(self._dcd, nm)
                st.add(nm, sig.shape().width)
                st.override[nm] = sig
            # gate stage-valid on a successful decode so invalid ops die
            st.override["valid"] = self._dcd.valid & prev.valid
            # RAW is now handled by the RF-stage bypsel forward (op_a/b/c
            # select FPR | ex-fwd | wb-fwd), NOT a stall — for this single-
            # cycle FU the producer is always at EX/WB (forwardable) by the
            # time a back-to-back consumer reaches RF. The scoreboard still
            # marks destinations busy for bookkeeping / a future multi-cycle
            # or unforwardable FU, where the stall returns.
            with m.If(prev.valid & self._dcd.valid & self._dcd.rt_v):
                m.d.sync += self.sb_busy.bit_select(self._dcd.rt, 1).eq(1)

        elif st.name == "rf":
            # carry control forward
            for nm in ("valid", "is_mul", "math_b", "sub_op_b", "inv_sign_b",
                       "from_int_b", "frsp_b", "fu_sel", "alu_op", "uses_simm",
                       "simm", "rt", "ra", "rb", "rc",
                       "ra_v", "rb_v", "rc_v", "rt_v"):
                sig = prev.payload[nm]
                st.add(nm, sig.shape().width)
            # operand regs with the bypsel forward (FPR | ex-fwd | wb-fwd)
            st.add("op_a", FPR_W); st.add("op_b", FPR_W); st.add("op_c", FPR_W)
            self._rf_fwd(m, st, prev)

        elif st.name == "ex":
            for nm in ("valid", "is_mul", "fu_sel", "alu_op", "rt", "rt_v"):
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

    # --- RF operand forward (the bypsel mux) -------------------------------
    def _rf_fwd(self, m, st, prev):
        """Per-source operand select: FPR | forward from EX | forward from WB.

        A dependent op reads its source register here. If that register is the
        destination of the op currently in EX or WB (a producer still ahead of
        the consumer), forward that result instead of the stale FPR value —
        the `iu_fu_rf0_bypsel` mux. Prefer the EX forward over WB for a match
        (EX is the younger producer in program order for a WAW pair).

        Producer stage handles:
          ex : self.stages[EX].payload  {rt, rt_v} + self._ex_result (comb)
          wb : self.stages[WB].payload  {rt, rt_v, result}
        """
        ex_rt = self.prod_ex_rt
        ex_rtv = self.prod_ex_rtv
        wb_rt = self.prod_wb_rt
        wb_rtv = self.prod_wb_rtv
        wb_res = self.prod_wb_res

        for src, out in (("ra", "op_a"), ("rb", "op_b"), ("rc", "op_c")):
            s = prev.payload[src].bit_select(0, 6)
            fpr_v = self.fpr[s]
            hit_ex = ex_rtv & (ex_rt == s)
            hit_wb = wb_rtv & (wb_rt == s)
            fwd = Signal(FPR_W, name=f"{st.name}_{src}_fwd")
            m.d.comb += fwd.eq(fpr_v)
            with m.If(hit_ex):
                m.d.comb += fwd.eq(self.prod_ex_res)
            with m.Elif(hit_wb):
                m.d.comb += fwd.eq(wb_res)
            st.override[out] = fwd

    # --- EX: the FU kernels (fuq_mul FP + xuq_alu_add GPR) ------------------
    def _build_ex(self, m, st, prev):
        fu_sel = prev.payload["fu_sel"]
        alu_op = prev.payload["alu_op"]
        uses_simm = prev.payload["uses_simm"]
        simm = prev.payload["simm"]

        # operand B: immediate form (addi/addis) substitutes the sign-extended
        # 16-bit SIMM for the RB register value.
        op_b = Signal(FPR_W, name="ex_op_b_sel")
        m.d.comb += op_b.eq(self.ex_op_b)
        with m.If(uses_simm):
            m.d.comb += op_b.eq(Cat(simm, simm[15].replicate(FPR_W - 16)))

        is_fpu = fu_sel == Const(FU_FPU, 2)
        is_alu = fu_sel == Const(FU_FXU_ADD, 2)

        # ---- FU: fuq_mul (FP multiply) ------------------------------------
        self._ex = Kernel(self.fu_kernel)
        m.submodules.ex_fu = k = self._ex
        act = getattr(k, "c_ex1_act", None)
        if act is not None:
            m.d.comb += act.eq(st.valid & is_fpu & ~st.flush & ~self.stall)
        fl = getattr(k, "c_flush", None)
        if fl is not None:
            m.d.comb += fl.eq(st.flush | self.flush_all)
        a = getattr(k, "p_f_fmt_ex1_a_frac", None)
        c = getattr(k, "p_f_fmt_ex1_c_frac", None)
        if a is not None:
            m.d.comb += a.eq(self.ex_op_a[:A_FRAC_W])
        if c is not None:
            m.d.comb += c.eq(self.ex_op_c[:C_FRAC_W])
        s = getattr(k, "p_f_mul_ex2_sum", None)
        r = getattr(k, "p_f_mul_ex2_car", None)
        fpu_res = Signal(FPR_W, name="fpu_res")
        if s is not None and r is not None:
            m.d.comb += fpu_res.eq(s[:FPR_W] + r[:FPR_W])

        # ---- FU: xuq_alu_add (GPR add/subf/cmp) ----------------------------
        self._alu = Kernel("xuq_alu_add")
        m.submodules.ex_alu = ka = self._alu
        aact = getattr(ka, "c_dec_alu_rf1_add_act", None)
        if aact is not None:
            m.d.comb += aact.eq(st.valid & is_alu & ~st.flush & ~self.stall)
        rs0 = getattr(ka, "p_byp_alu_ex1_rs0", None)
        rs1 = getattr(ka, "p_byp_alu_ex1_rs1", None)
        if rs0 is not None:
            m.d.comb += rs0.eq(self.ex_op_a)
        if rs1 is not None:
            m.d.comb += rs1.eq(op_b)
        inv = getattr(ka, "p_dec_alu_rf1_add_rs0_inv", None)
        if inv is not None:
            # rs0_inv is a 64-bit per-bit XOR MASK (x_b = aop ^ rs0_inv), not a
            # flag: all-ones inverts rs0 so ~rs0 + rs1 + ci = rs1 - rs0 (subf);
            # all-zeros passes rs0 through (add/cmp).
            m.d.comb += inv.eq(Mux(alu_op == Const(ALUOP_SUBF, 2),
                                   Const(-1, FPR_W), Const(0, FPR_W)))
        ci = getattr(ka, "p_dec_alu_rf1_add_ci", None)
        if ci is not None:
            m.d.comb += ci.eq(alu_op == Const(ALUOP_SUBF, 2))
        for nm, val in (("p_dec_alu_rf1_select_64bmode", 1),
                        ("p_dec_alu_rf1_is_cmpl", 0),
                        ("p_dec_alu_rf1_tw_cmpsel", 0),
                        ("p_dec_alu_ex1_is_cmp", alu_op == Const(ALUOP_CMP, 2)),
                        ("p_log_add_ex2_rt", 0),
                        ("p_dec_ex2_tid", 0), ("p_dec_ex4_tid", 0),
                        ("p_spr_msr_cm", 1)):
            p = getattr(ka, nm, None)
            if p is not None:
                m.d.comb += p.eq(val)
        alu_rt = getattr(ka, "p_alu_byp_ex2_rt", None)
        alu_res = Signal(FPR_W, name="alu_res")
        if alu_rt is not None:
            m.d.comb += alu_res.eq(alu_rt)

        # ---- result mux by FU + publish producer for the rf forward -------
        m.d.comb += self._ex_result.eq(Mux(is_alu, alu_res, fpu_res))
        # EX stage's OWN registered fields — at the cycle a consumer is in rf,
        # the producer is in ex holding its rt.
        m.d.comb += self.prod_ex_res.eq(self._ex_result)
        m.d.comb += self.prod_ex_rt.eq(st.payload["rt"].bit_select(0, 6))
        m.d.comb += self.prod_ex_rtv.eq(st.valid & st.payload["rt_v"])

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
        # publish this op as a WB-stage producer for the rf forward
        m.d.comb += self.prod_wb_rt.eq(rt)
        m.d.comb += self.prod_wb_rtv.eq(st.valid & st.payload["rt_v"])
        m.d.comb += self.prod_wb_res.eq(st.payload["result"])
        # architected writeback into the FPR + scoreboard clear (always-ready
        # write port in v1; a real RF may add backpressure later)
        with m.If(st.valid & st.payload["rt_v"]):
            m.d.sync += self.fpr[rt].eq(st.payload["result"])
            m.d.sync += self.sb_busy.bit_select(rt, 1).eq(0)
        # external FPR preload (test vectors / LSU)
        with m.If(self.fpr_we):
            m.d.sync += self.fpr[self.fpr_waddr].eq(self.fpr_wdata)
            m.d.sync += self.sb_busy.bit_select(self.fpr_waddr, 1).eq(0)
