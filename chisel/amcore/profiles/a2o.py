"""A2O profile — out-of-order pipeline skeleton sharing the kernel set.

Stage sequence (v1 skeleton):
    dispatch -> rename -> RS (reservation station) -> issue -> EX -> CDB -> complete

v1 scope: a single reservation-station entry + one EX kernel (`fuq_mul`),
so the OoO plumbing (tag allocation, operand-ready wakeup, out-of-order
result on the CDB, in-order completion) is exercised against the same golden
kernel the in-order profile uses. Breadth (multiple RS entries, multiple FUs,
real rename) layers on later.
"""

from __future__ import annotations

from amaranth import Array, Module, Signal

from ..kernel import Kernel
from ..pipeline import PipelineSkeleton, Stage

STAGES = ["disp", "rn", "rs", "iss", "ex", "cdb", "cpl"]

# v1: a single tag width covering the rename/completion tag space.
TAG_W = 6


class OoOCore(PipelineSkeleton):
    """Minimal out-of-order core wrapping a single frozen EX kernel.

    Adds the OoO-only machinery on top of the shared skeleton:
      - a small reservation-station entry (busy, opcode, operand tags+values)
      - tag-based operand-ready wakeup (producer tag -> ready)
      - a common-data-bus result (tag + value) consumed by the wakeup
    """

    PROFILE = "a2o"

    def __init__(self, fu_kernel: str = "fuq_mul", tag_w: int = TAG_W):
        super().__init__(STAGES)
        self.fu_kernel = fu_kernel
        self.tag_w = tag_w
        # reservation-station entry (v1: one)
        self.rs_busy = Signal(name="rs_busy")
        self.rs_op = Signal(8, name="rs_op")
        self.rs_atag = Signal(tag_w, name="rs_atag")   # src-A producer tag
        self.rs_btag = Signal(tag_w, name="rs_btag")   # src-B producer tag
        self.rs_aready = Signal(name="rs_aready")
        self.rs_bready = Signal(name="rs_bready")
        # common data bus (result broadcast)
        self.cdb_tag = Signal(tag_w, name="cdb_tag")
        self.cdb_val = Signal(64, name="cdb_val")
        self.cdb_valid = Signal(name="cdb_valid")

    def ports(self):
        from amaranth.hdl import IOPort
        return [
            IOPort(self.tag_w, name="cdb_tag"),
            IOPort(64, name="cdb_val"),
            IOPort(1, name="cdb_valid"),
            IOPort(1, name="stall"),
            IOPort(1, name="flush_all"),
        ]

    def wire_stage(self, m: Module, i: int, st: Stage, prev):
        super().wire_stage(m, i, st, prev)
        if st.name == "rs":
            # wakeup: a CDB broadcast matching a pending src tag marks it ready
            with m.If(self.cdb_valid & (self.cdb_tag == self.rs_atag)):
                m.d.sync += self.rs_aready.eq(1)
            with m.If(self.cdb_valid & (self.cdb_tag == self.rs_btag)):
                m.d.sync += self.rs_bready.eq(1)
        elif st.name == "ex":
            self._ex = Kernel(self.fu_kernel)
            m.submodules.ex_fu = self._ex
            act = getattr(self._ex, "c_ex1_act", None)
            if act is None:
                act = getattr(self._ex, "p_ex1_act", None)
            if act is not None:
                m.d.comb += act.eq(st.valid & self.rs_aready & self.rs_bready)
