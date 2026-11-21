"""Parameterized pipeline skeleton shared by the in-order (a2i) and
out-of-order (a2o) profiles. Both profiles reuse:

  - Kernel blackbox wrappers (kernel.py) for the frozen datapath units
  - a valid/flush stage-enable chain around each EX-stage kernel
  - operand staging registers + a result writeback path

The skeleton is intentionally minimal for v1: a single functional unit class
(e.g. a multiplier) routed through the stage sequence so the plumbing —
decode -> operand select -> EX kernel -> writeback — is exercised end to end
against a golden kernel, before ISA breadth is added.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from amaranth import Const, Elaboratable, Module, Signal

from .kernel import Kernel


@dataclass
class Stage:
    """One pipeline stage: a named valid bit + a bank of payload signals.

    `valid` gates the stage-enable (A2I `*_act` convention); `payload` holds
    the registered values passed to the next stage. `flush` squashes the stage.
    """

    name: str
    valid: Signal = field(default_factory=Signal)
    flush: Signal = field(default_factory=Signal)
    payload: dict = field(default_factory=dict)
    # field name -> Value: source override. When set, the stage registers
    # this expression instead of forwarding prev.payload[name]. Still inside
    # the ~stall / ~flush envelope, so stall semantics are preserved.
    override: dict = field(default_factory=dict)

    def add(self, signame: str, width: int) -> Signal:
        s = Signal(width, name=f"{self.name}_{signame}")
        self.payload[signame] = s
        return s


class PipelineSkeleton(Elaboratable):
    """N-stage skeleton; subclass profiles wire the actual control.

    `stages` is the ordered list; `advance`/`stall`/`flush` are the generic
    controls a profile drives. The default connectivity registers `valid` and
    `payload` forward each cycle when not stalled; profiles override
    `wire_stage` to insert kernel + bypass logic at a stage.
    """

    PROFILE = "base"

    def __init__(self, stage_names: List[str]):
        self.stages = [Stage(n) for n in stage_names]
        self.stall = Signal()
        self.flush_all = Signal()

    # --- hooks a profile overrides -------------------------------------
    def wire_stage(self, m: Module, i: int, st: Stage, prev: Optional[Stage]):
        """Register `st` from `prev` (valid + payload). Default = straight
        feedthrough with stall/flush; profiles override to add logic."""
        with m.If(self.flush_all | st.flush):
            m.d.sync += st.valid.eq(0)
        with m.Elif(~self.stall):
            if prev is None:
                m.d.sync += st.valid.eq(1)   # source stage
            else:
                m.d.sync += st.valid.eq(prev.valid)
            for name, s in st.payload.items():
                if name in st.override:
                    m.d.sync += s.eq(st.override[name])
                elif prev is not None and name in prev.payload:
                    m.d.sync += s.eq(prev.payload[name])
    # --------------------------------------------------------------------

    def elaborate(self, platform):
        m = Module()
        prev: Optional[Stage] = None
        for i, st in enumerate(self.stages):
            self.wire_stage(m, i, st, prev)
            prev = st
        return m
