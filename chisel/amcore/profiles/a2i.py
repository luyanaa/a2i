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
                         FU_FPU, FU_FXU_ADD, FU_AGEN, FU_FXU_LOG, FU_FXU_MUL,
                         FU_FXU_DIV,
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
        # multi-cycle-FU writeback state: launch once, hold the op in EX until
        # the kernel's done flag, capture the (possibly 1-cycle) product, then
        # advance. busy=FU in flight; done_d = done delayed 1 cyc so the
        # product pulse has settled into *_hold.
        self.mc_busy = Signal(name="mc_busy")
        self.mc_done_d = Signal(name="mc_done_d")
        self.mc_res_hold = Signal(FPR_W, name="mc_res_hold")
        # destination of the in-flight multi-cycle op: a dependent that reads
        # it must stall in RF (the producer's forward is gated off while busy).
        self.mc_rt = Signal(6, name="mc_rt")
        # set while a mul/div op is resident in EX (launch through the cycle it
        # advances on done). Distinct from mc_busy (FU in flight): mc_issue also
        # covers the launch cycle itself so the val pulse fires exactly once and
        # the op can't slip a stage before the hold engages.
        self.mc_issue = Signal(name="mc_issue")
        # latches "the resident op completed and left EX": while set, a still-
        # asserted st.valid is the held op's stale valid (upstream re-filled the
        # slot), not a new arrival — so mc_launch must not re-arm. Clears once
        # st.valid drops or on flush.
        self.mc_drain = Signal(name="mc_drain")
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
            # capture the instruction word + its presence flag; `id` decodes
            # it combinationally. iv lets id gate validity on a real fetch
            # (instr_v=0 => no new op, so downstream bubbles rather than
            # re-decoding the stale held word).
            st.add("instr", 32)
            st.add("iv", 1)
            st.override["instr"] = self.instr
            st.override["iv"] = self.instr_v

        elif st.name == "id":
            # decode runs comb on the if-staged instruction -> control bundle
            st.add("instr", 32)
            st.add("iv", 1)
            self._dcd.emit(m, prev.payload["instr"])
            for nm in ("valid", "is_mul", "math_b", "sub_op_b", "inv_sign_b",
                       "from_int_b", "frsp_b", "fu_sel", "alu_op", "uses_simm",
                       "simm", "log_fcn", "mul_ret", "mul_size", "mul_imm",
                       "mul_sign", "div_sign", "div_size", "div_extd", "div_ctr",
                       "rt", "ra", "rb", "rc",
                       "ra_v", "rb_v", "rc_v", "rt_v"):
                sig = getattr(self._dcd, nm)
                st.add(nm, sig.shape().width)
                st.override[nm] = sig
            # gate stage-valid on a successful decode *and* a real fetched
            # instruction (iv): instr_v=0 means no new op, so the stale held
            # word must not re-enter the pipe as a phantom.
            st.override["valid"] = self._dcd.valid & prev.valid & prev.payload["iv"]
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
                       "simm", "log_fcn", "mul_ret", "mul_size", "mul_imm",
                       "mul_sign", "div_sign", "div_size", "div_extd", "div_ctr",
                       "rt", "ra", "rb", "rc",
                       "ra_v", "rb_v", "rc_v", "rt_v"):
                sig = prev.payload[nm]
                st.add(nm, sig.shape().width)
            # operand regs with the bypsel forward (FPR | ex-fwd | wb-fwd)
            st.add("op_a", FPR_W); st.add("op_b", FPR_W); st.add("op_c", FPR_W)
            self._rf_fwd(m, st, prev)
            # interlock: stall a consumer that reads the in-flight multi-cycle
            # producer's destination (its forward is gated while mc_busy, so it
            # must wait for the product rather than consume a stale FPR value).
            needs = []
            for src, v in (("ra", "ra_v"), ("rb", "rb_v"), ("rc", "rc_v")):
                if v in prev.payload:
                    s = prev.payload[src].bit_select(0, 6)
                    needs.append(prev.payload[v] & (s == self.mc_rt))
            dep = Signal(name="rf_mc_dep")
            m.d.comb += dep.eq(
                (needs[0] | needs[1] | needs[2]) if needs else Const(0))
            m.d.comb += st.stall.eq(prev.valid & self.mc_busy & dep)

        elif st.name == "ex":
            for nm in ("valid", "is_mul", "fu_sel", "alu_op", "log_fcn",
                       "mul_ret", "mul_size", "mul_imm", "mul_sign",
                       "div_sign", "div_size", "div_extd", "div_ctr",
                       "rt", "rt_v"):
                sig = prev.payload[nm]
                st.add(nm, sig.shape().width)
            # register the operands into EX (the f_fmt_ex1_* contract)
            m.d.sync += self.ex_op_a.eq(prev.payload["op_a"])
            m.d.sync += self.ex_op_b.eq(prev.payload["op_b"])
            m.d.sync += self.ex_op_c.eq(prev.payload["op_c"])
            self._build_ex(m, st, prev)

        elif st.name == "wb":
            st.add("valid", 1)
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
            # immediate form (addi/lwz/...): operand B <- sign-extended SIMM,
            # resolved HERE so ex's kernel sees it registered, not recomputed
            # from next-cycle rf fields.
            if out == "op_b" and "uses_simm" in prev.payload:
                simm = prev.payload["simm"]
                imm = Cat(simm, simm[15].replicate(FPR_W - 16))
                st.override[out] = Mux(prev.payload["uses_simm"], imm, fwd)
            else:
                st.override[out] = fwd

    # --- EX: the FU kernels (fuq_mul FP + xuq_alu_add GPR) ------------------
    def _build_ex(self, m, st, prev):
        fu_sel = prev.payload["fu_sel"]
        alu_op = prev.payload["alu_op"]
        # operands are resolved at rf (forward + SIMM substitute) and arrive
        # registered: ex_op_a/b already hold the final values for the kernels.
        op_b = self.ex_op_b

        is_fpu = fu_sel == Const(FU_FPU, 3)
        is_alu = fu_sel == Const(FU_FXU_ADD, 3)
        is_agen = fu_sel == Const(FU_AGEN, 3)
        is_log = fu_sel == Const(FU_FXU_LOG, 3)
        is_mul = fu_sel == Const(FU_FXU_MUL, 3)
        is_div = fu_sel == Const(FU_FXU_DIV, 3)

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

        # ---- FU: xuq_agen (load/store effective address = RA + SIMM) -------
        self._agen = Kernel("xuq_agen")
        m.submodules.ex_agen = kg = self._agen
        gx = getattr(kg, "p_x", None); gy = getattr(kg, "p_y", None)
        if gx is not None:
            m.d.comb += gx.eq(self.ex_op_a)      # RA base
        if gy is not None:
            m.d.comb += gy.eq(op_b)              # SIMM displacement
        for nm, val in (("p_mode64", 1), ("p_snoop_sel", 0), ("p_binv_val", 0),
                        ("p_dir_ig_57_b", 0), ("p_snoop_addr", 0),
                        ("p_z", 0), ("p_way", 0), ("p_inv1_val_b", 0),
                        ("p_ex1_cache_acc_b", 0), ("p_rel3_val", 0)):
            p = getattr(kg, nm, None)
            if p is not None:
                m.d.comb += p.eq(val)
        ea = getattr(kg, "p_sum_non_erat", None)   # 64b effective address
        agen_res = Signal(FPR_W, name="agen_res")
        if ea is not None:
            m.d.comb += agen_res.eq(ea)

        # ---- FU: xuq_alu logic unit (GPR logicals) -------------------------
        self._alu_log = Kernel("xuq_alu")
        m.submodules.ex_alu_log = kl = self._alu_log
        lrf1 = getattr(kl, "c_dec_alu_rf1_act", None)
        lex1 = getattr(kl, "c_dec_alu_ex1_act", None)
        if lrf1 is not None:
            m.d.comb += lrf1.eq(st.valid & is_log & ~st.flush & ~self.stall)
        if lex1 is not None:
            m.d.comb += lex1.eq(st.valid & is_log & ~st.flush & ~self.stall)
        ls0 = getattr(kl, "p_byp_alu_ex1_rs0", None)
        ls1 = getattr(kl, "p_byp_alu_ex1_rs1", None)
        if ls0 is not None:
            m.d.comb += ls0.eq(self.ex_op_a)
        if ls1 is not None:
            m.d.comb += ls1.eq(op_b)
        # mul operands: ex1-comb reads (byp_alu_ex1_mulsrc_*)
        ms0 = getattr(kl, "p_byp_alu_ex1_mulsrc_0", None)
        ms1 = getattr(kl, "p_byp_alu_ex1_mulsrc_1", None)
        if ms0 is not None:
            m.d.comb += ms0.eq(self.ex_op_a)
        if ms1 is not None:
            m.d.comb += ms1.eq(op_b)
        # div operands: dividend=RA (divsrc_0), divisor=RB (divsrc_1), ex1-comb
        ds0 = getattr(kl, "p_byp_alu_ex1_divsrc_0", None)
        ds1 = getattr(kl, "p_byp_alu_ex1_divsrc_1", None)
        if ds0 is not None:
            m.d.comb += ds0.eq(self.ex_op_a)
        if ds1 is not None:
            m.d.comb += ds1.eq(op_b)
        lsel = getattr(kl, "p_dec_alu_rf1_sel", None)
        if lsel is not None:
            # sel(0)=1 picks the ADD subunit; 0 = rot/log. Mul is gated by its
            # own dec_alu_rf1_mul_val, not by sel — keep 0 for log+mul.
            m.d.comb += lsel.eq(Const(0, 4))
        lfcn = getattr(kl, "p_dec_alu_rf1_log_fcn", None)
        if lfcn is not None:
            m.d.comb += lfcn.eq(prev.payload["log_fcn"])
        # mul controls + div controls (rf1-latched)
        for nm, fld in (("p_dec_alu_rf1_mul_ret", "mul_ret"),
                        ("p_dec_alu_rf1_mul_size", "mul_size"),
                        ("p_dec_alu_rf1_mul_imm", "mul_imm"),
                        ("p_dec_alu_rf1_mul_sign", "mul_sign"),
                        ("p_dec_alu_rf1_div_sign", "div_sign"),
                        ("p_dec_alu_rf1_div_size", "div_size"),
                        ("p_dec_alu_rf1_div_extd", "div_extd"),
                        ("p_fxa_fxb_rf1_div_ctr", "div_ctr")):
            p = getattr(kl, nm, None)
            if p is not None:
                m.d.comb += p.eq(prev.payload[fld])
        # mul/div results (kernel outputs; multi-cycle — valid on their done
        # flags, not the launch cycle)
        mrt = getattr(kl, "p_alu_byp_ex5_mul_rt", None)
        mul_res = Signal(FPR_W, name="mul_res")
        if mrt is not None:
            m.d.comb += mul_res.eq(mrt)
        drt = getattr(kl, "p_alu_byp_ex3_div_rt", None)
        div_res = Signal(FPR_W, name="div_res")
        if drt is not None:
            m.d.comb += div_res.eq(drt)

        # ---- multi-cycle launch/done handshake ----------------------------
        # A mul/div launches ONCE when it enters EX (mul_val/div_val are level-
        # sensitive loaders — re-pulsing reloads operands and never iterates).
        # mc_busy marks in-flight; the op is held in EX (st.stall) until done,
        # the product is captured into mc_res_hold, then it advances.
        mval = getattr(kl, "c_dec_alu_rf1_mul_val", None)
        dval = getattr(kl, "c_dec_alu_rf1_div_val", None)
        mdone = getattr(kl, "p_alu_ex4_mul_done", None)
        ddone = getattr(kl, "p_alu_ex2_div_done", None)
        # done this cycle (kernel flag); the product lands ~1 cyc later.
        # Declared before mc_launch: a launch must not re-fire on the done
        # cycle (the resident op is leaving EX, not a new one entering).
        mc_done = Signal(name="mc_done")
        m.d.comb += mc_done.eq(
            (is_mul & (mdone if mdone is not None else Const(0))) |
            (is_div & (ddone if ddone is not None else Const(0))))
        # ex_vld is the *payload* valid (decode-gated on a real fetched instr):
        # it drops once the held op drains so a stale held word can't re-launch.
        ex_vld = st.payload["valid"]
        mc_launch = ex_vld & (is_mul | is_div) & ~self.mc_issue \
                    & ~self.mc_drain & ~mc_done & ~st.flush & ~self.stall
        if mval is not None:
            m.d.comb += mval.eq(mc_launch & is_mul)
        if dval is not None:
            m.d.comb += dval.eq(mc_launch & is_div)
        # busy set on launch, cleared after the product is captured (done_d)
        m.d.sync += self.mc_done_d.eq(mc_done)
        with m.If(st.flush | self.flush_all):
            m.d.sync += self.mc_busy.eq(0)
        with m.Elif(self.mc_done_d):
            m.d.sync += self.mc_busy.eq(0)
        with m.Elif(mc_launch):
            m.d.sync += self.mc_busy.eq(1)
        # mc_issue marks the op resident in EX from its launch cycle until it
        # advances on done. Cleared by flush or on the done cycle itself.
        # mc_drain (declared in __init__) blocks a re-launch off the held op's
        # stale st.valid; clears once st.valid drops or on flush.
        with m.If(st.flush | self.flush_all):
            m.d.sync += self.mc_issue.eq(0)
            m.d.sync += self.mc_drain.eq(0)
        with m.Elif(mc_done):
            m.d.sync += self.mc_issue.eq(0)
            m.d.sync += self.mc_drain.eq(1)
        with m.Elif(~ex_vld):
            m.d.sync += self.mc_drain.eq(0)
        with m.Elif(mc_launch):
            m.d.sync += self.mc_issue.eq(1)
        # hold the op in EX (bubble into WB) from its launch cycle until done;
        # release on mc_done so it advances carrying the captured product.
        # mc_issue (not mc_busy) covers the launch cycle so the op can't slip a
        # stage before the hold engages.
        m.d.comb += st.stall.eq(
            ex_vld & (is_mul | is_div) & (self.mc_issue | mc_launch)
            & ~mc_done)
        with m.If(mc_done | self.mc_done_d):
            m.d.sync += self.mc_res_hold.eq(Mux(is_div, div_res, mul_res))
        # remember which register the in-flight op will write, so a dependent
        # in RF stalls (its forward is gated off until the product is ready).
        with m.If(mc_launch):
            m.d.sync += self.mc_rt.eq(st.payload["rt"].bit_select(0, 6))
        # tie off the shift/isel + compare machinery (unused by log/mul/div)
        for nm, val in (
                ("p_spr_msr_cm", 1), ("p_dec_alu_rf1_add_rs0_inv", 0),
                ("p_dec_alu_rf1_add_ci", 0), ("p_dec_alu_rf1_is_cmpl", 0),
                ("p_dec_alu_rf1_tw_cmpsel", 0), ("p_dec_ex2_tid", 0),
                ("p_dec_ex4_tid", 0), ("p_dec_alu_rf1_mul_recform", 0),
                ("p_dec_alu_rf1_div_recform", 0), ("p_dec_alu_ex1_is_cmp", 0),
                ("p_dec_alu_rf1_select_64bmode", 1),
                ("c_fxa_fxb_ex1_hold_ctr_flush", 0),
                ("p_byp_alu_rf1_isel_fcn", 0), ("p_dec_alu_rf1_sh_amt", 0),
                ("p_dec_alu_rf1_mb_ins", 0), ("p_dec_alu_rf1_me_ins_b", 0),
                ("p_dec_alu_rf1_mb_gt_me", 0)):
            p = getattr(kl, nm, None)
            if p is not None:
                m.d.comb += p.eq(val)
        log_rt = getattr(kl, "p_alu_byp_ex1_log_rt", None)
        log_res = Signal(FPR_W, name="log_res")
        if log_rt is not None:
            m.d.comb += log_res.eq(log_rt)

        # ---- result mux by FU + publish producer for the rf forward -------
        # mul/div are multi-cycle: the op is held in EX until done and the
        # product is latched into mc_res_hold, so _ex_result reads the held
        # product (not the transient kernel output) when it advances.
        m.d.comb += self._ex_result.eq(
            Mux(is_alu, alu_res,
                Mux(is_agen, agen_res,
                    Mux(is_log, log_res,
                        Mux(is_mul | is_div, self.mc_res_hold, fpu_res)))))
        # EX stage's OWN registered fields — at the cycle a consumer is in rf,
        # the producer is in ex holding its rt.
        m.d.comb += self.prod_ex_res.eq(self._ex_result)
        m.d.comb += self.prod_ex_rt.eq(st.payload["rt"].bit_select(0, 6))
        # don't advertise a mul/div result to the rf forward while its
        # multi-cycle FU is still in flight (mc_res_hold isn't the product yet)
        m.d.comb += self.prod_ex_rtv.eq(
            st.valid & st.payload["rt_v"] &
            ~((is_mul | is_div) & self.mc_busy))

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
        # the gated payload valid (a real op reached WB), not the always-1
        # stage register — prevents a drained multi-cycle op's stale EX slot
        # from re-writing the register file every cycle.
        wvld = st.payload["valid"]
        m.d.comb += self.wb_valid.eq(wvld & st.payload["rt_v"])
        # publish this op as a WB-stage producer for the rf forward
        m.d.comb += self.prod_wb_rt.eq(rt)
        m.d.comb += self.prod_wb_rtv.eq(wvld & st.payload["rt_v"])
        m.d.comb += self.prod_wb_res.eq(st.payload["result"])
        # architected writeback into the FPR + scoreboard clear (always-ready
        # write port in v1; a real RF may add backpressure later)
        with m.If(wvld & st.payload["rt_v"]):
            m.d.sync += self.fpr[rt].eq(st.payload["result"])
            m.d.sync += self.sb_busy.bit_select(rt, 1).eq(0)
        # external FPR preload (test vectors / LSU)
        with m.If(self.fpr_we):
            m.d.sync += self.fpr[self.fpr_waddr].eq(self.fpr_wdata)
            m.d.sync += self.sb_busy.bit_select(self.fpr_waddr, 1).eq(0)
