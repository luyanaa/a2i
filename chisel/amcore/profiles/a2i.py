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


class InOrderCore(PipelineSkeleton):
    """Minimal in-order core wrapping a single frozen EX kernel.

    Params:
      fu_kernel: manifest entity name for the EX stage (default 'fuq_mul').
      threads:   hardware thread count (scoreboard is per-thread; v1 = 1).

    The EX stage instantiates `Kernel(fu_kernel)`; `rf` presents operands,
    `wb` writes the (carry-save or final) result back. A per-dest scoreboard
    bit provides the RAW interlock that an in-order machine needs to stall
    a consumer until the producer writes back.
    """

    PROFILE = "a2i"

    def __init__(self, fu_kernel: str = "fuq_mul", threads: int = 1):
        super().__init__(STAGES)
        self.fu_kernel = fu_kernel
        self.threads = threads
        # instruction/operand interfaces a testbench or upstream stage drives
        self.fetch_instr = Signal(32, name="fetch_instr")
        self.rd_data = Signal(64, name="wb_rd_data")   # architectural writeback
        # scoreboard: dest-reg busy bits (interlock for in-order)
        self.sb_busy = Signal(64, name="sb_busy")      # 1 bit per GPR, v1 small

    def wire_stage(self, m: Module, i: int, st: Stage, prev):
        super().wire_stage(m, i, st, prev)
        if st.name == "ex":
            # the kernel is the EX stage; ex1_act = stage-valid (A2I convention)
            self._ex = Kernel(self.fu_kernel)
            m.submodules.ex_fu = self._ex
            act = getattr(self._ex, "c_ex1_act", None)
            if act is None:
                act = getattr(self._ex, "p_ex1_act", None)
            if act is not None:
                m.d.comb += act.eq(st.valid & ~st.flush & ~self.stall)
