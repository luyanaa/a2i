"""A2I profile — in-order pipeline, matching the frozen a2x_axi datapath.

Stage sequence (v1, single-FU skeleton):
    IF (fetch) -> ID (decode) -> RF (operand read) -> EX (kernel) -> WB

v1 scope: a single instruction class routed through `fuq_mul` as the EX
kernel, so the in-order plumbing (valid chain, operand staging, scoreboard
RAW interlock, writeback) is exercised end to end. ISA breadth is layered on
top of this skeleton, not into it.
"""

from __future__ import annotations

from amaranth import Module, Signal

from ..kernel import Kernel
from ..pipeline import PipelineSkeleton, Stage

# A2I in-order stage order; EX is where a kernel lives.
STAGES = ["if", "id", "rf", "ex", "wb"]

# fuq_mul operand/result widths (from manifest).
A_FRAC_W = 53   # f_fmt_ex1_a_frac  : std_ulogic_vector(0 to 52)
C_FRAC_W = 54   # f_fmt_ex1_c_frac  : std_ulogic_vector(0 to 53)
PROD_W = 108    # f_mul_ex2_sum/car : std_ulogic_vector(1 to 108)


class InOrderCore(PipelineSkeleton):
    """Minimal in-order core wrapping a single frozen EX kernel.

    Params:
      fu_kernel: manifest entity name for the EX stage (default 'fuq_mul').
      threads:   hardware thread count (scoreboard is per-thread; v1 = 1).

    Data path (v1, fuq_mul):
      rf -> ex : a_frac, c_frac operand fields staged into the kernel.
      ex -> wb : carry-save product (sum + car) captured for writeback.
      A per-dest scoreboard bit provides the RAW interlock that an in-order
      machine needs to stall a consumer until the producer writes back.
    """

    PROFILE = "a2i"

    def __init__(self, fu_kernel: str = "fuq_mul", threads: int = 1):
        super().__init__(STAGES)
        self.fu_kernel = fu_kernel
        self.threads = threads

        # ---- architectural interfaces a TB / upstream drives -------------
        self.fetch_instr = Signal(32, name="fetch_instr")
        # RF-stage source operands presented by the register-read + bypass
        # select logic (driven externally in v1, RF/bypass generated later).
        self.rf_op_a = Signal(64, name="rf_op_a")   # operand A (multiplier)
        self.rf_op_c = Signal(64, name="rf_op_c")   # operand C (multiplicand)
        # writeback result exposed to the architectural RF
        self.wb_data = Signal(64, name="wb_data")
        self.wb_valid = Signal(name="wb_valid")
        # scoreboard: 1 busy bit per GPR (v1 keeps it small/simple)
        self.sb_busy = Signal(32, name="sb_busy")

        self._ex: Kernel | None = None
        # ex-stage operand registers (separate from generic payload so the
        # skeleton's default forward-register doesn't fight our drivers).
        self.ex_op_a = Signal(64, name="ex_op_a")
        self.ex_op_c = Signal(64, name="ex_op_c")

    # --- EX stage: instantiate the kernel, drive its act + operands ------
    def wire_stage(self, m: Module, i: int, st: Stage, prev):
        super().wire_stage(m, i, st, prev)
        if st.name != "ex":
            return
        # operands are *produced* at RF (register-read + bypass, external in
        # v1). Register them into the EX stage's operand regs so the kernel
        # sees ex1-staged values (the f_fmt_ex1_* contract).
        m.d.sync += self.ex_op_a.eq(self.rf_op_a)
        m.d.sync += self.ex_op_c.eq(self.rf_op_c)

        self._ex = Kernel(self.fu_kernel)
        m.submodules.ex_fu = self._ex
        k = self._ex

        # stage-enable (A2I *_act convention): valid, not flushed, not stalled
        act = getattr(k, "c_ex1_act", None)
        if act is not None:
            m.d.comb += act.eq(st.valid & ~st.flush & ~self.stall)
        flush = getattr(k, "c_flush", None)
        if flush is not None:
            m.d.comb += flush.eq(st.flush | self.flush_all)

        # operand routing (fuq_mul contract): ex-staged operand regs -> frac
        # fields. v1 truncates to field widths; a real decode supplies the
        # formatted fraction.
        a = getattr(k, "p_f_fmt_ex1_a_frac", None)
        c = getattr(k, "p_f_fmt_ex1_c_frac", None)
        if a is not None:
            m.d.comb += a.eq(self.ex_op_a[:A_FRAC_W])
        if c is not None:
            m.d.comb += c.eq(self.ex_op_c[:C_FRAC_W])

        # carry-save product -> writeback staging. v1 exposes sum+car folded
        # into a single 64b architectural value via a placeholder CPA
        # (fuq_mul's real output model is a*c + 2^107 for sparse multipliers;
        # the exact CPA/normalize is a datapath-correctness follow-up).
        s = getattr(k, "p_f_mul_ex2_sum", None)
        r = getattr(k, "p_f_mul_ex2_car", None)
        wb = self.stages[STAGES.index("wb")]
        if s is not None and r is not None:
            m.d.sync += self.wb_data.eq((s[:64] + r[:64]))  # carry-save fold
            m.d.sync += self.wb_valid.eq(st.valid)
