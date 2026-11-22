"""A2O profile — out-of-order pipeline over the same golden kernel set.

Stage sequence (v1 skeleton):
    disp(decode+rename) -> rs(reservation station) -> issue -> ex -> cdb -> cpl

Shares with a2i: the PPC64 decode -> `Decoded` bundle and the `fuq_mul` Kernel.
Differs in control: instead of a scoreboard+interlock, a destination gets a
rename TAG, the op sits in a reservation station until its operand tags are
ready (woken by a CDB broadcast), issues out-of-order, and broadcasts its
result (tag+value) on the common data bus. v1 = one RS entry + one FU so the
tag/wakeup/CDB plumbing is exercised end to end against the same kernel.
"""

from __future__ import annotations

from amaranth import Array, Const, Module, Mux, Signal

from ..isa.ppc64 import Decoded, SEL_FCFID, SEL_FMADD_SUB, SEL_FMUL
from ..kernel import Kernel
from ..pipeline import PipelineSkeleton, Stage

STAGES = ["disp", "rs", "iss", "ex", "cdb", "cpl"]

TAG_W = 6           # rename-tag space (v1: a few in-flight ops)
NRS = 4             # reservation-station entries
A_FRAC_W = 53
C_FRAC_W = 54
FPR_W = 64


class OoOCore(PipelineSkeleton):
    """Minimal out-of-order core: decode+rename -> RS -> issue -> fuq_mul -> CDB.

    External interface (v1): drive `instr`+`instr_v`; the core decodes,
    allocates a tag for the destination, holds the op in the RS until its
    operand tags are ready, issues it to `fuq_mul`, and broadcasts
    (cdb_tag, cdb_val) which wakes any waiting consumer. `cpl` retires it.
    """

    PROFILE = "a2o"

    def __init__(self, fu_kernel: str = "fuq_mul", tag_w: int = TAG_W):
        super().__init__(STAGES)
        self.fu_kernel = fu_kernel
        self.tag_w = tag_w

        # ---- upstream interface ------------------------------------------
        self.instr = Signal(32, name="instr")
        self.instr_v = Signal(name="instr_v")

        # ---- rename: physical regfile (PRF) + map table (arch->phys) ------
        self.nprf = 64
        self.prf = Array(Signal(FPR_W, name=f"prf{i}") for i in range(self.nprf))
        # map table: arch reg -> physical tag (v1: identity-ish, tags = prf idx)
        self.map = Array(Signal(tag_w, name=f"mt{i}") for i in range(64))
        self.freelist = Signal(self.nprf, name="freelist")   # 1 = free
        self.tag_busy = Signal(64, name="tag_busy")   # in-flight producer tags

        # ---- reservation station entries --------------------------------
        self.rs_busy = Array(Signal(name=f"rs{i}_busy") for i in range(NRS))
        self.rs_op = Array(Signal(2, name=f"rs{i}_op") for i in range(NRS))
        self.rs_dt = Array(Signal(tag_w, name=f"rs{i}_dt") for i in range(NRS))  # dest tag
        self.rs_at = Array(Signal(tag_w, name=f"rs{i}_at") for i in range(NRS))  # src A tag
        self.rs_bt = Array(Signal(tag_w, name=f"rs{i}_bt") for i in range(NRS))  # src B tag
        self.rs_ct = Array(Signal(tag_w, name=f"rs{i}_ct") for i in range(NRS))  # src C tag
        self.rs_av = Array(Signal(FPR_W, name=f"rs{i}_av") for i in range(NRS))  # src A value
        self.rs_bv = Array(Signal(FPR_W, name=f"rs{i}_bv") for i in range(NRS))
        self.rs_cv = Array(Signal(FPR_W, name=f"rs{i}_cv") for i in range(NRS))
        self.rs_ar = Array(Signal(name=f"rs{i}_ar") for i in range(NRS))  # A ready
        self.rs_br = Array(Signal(name=f"rs{i}_br") for i in range(NRS))
        self.rs_cr = Array(Signal(name=f"rs{i}_cr") for i in range(NRS))

        # ---- common data bus (result broadcast + wakeup) ----------------
        self.cdb_tag = Signal(tag_w, name="cdb_tag")
        self.cdb_val = Signal(FPR_W, name="cdb_val")
        self.cdb_valid = Signal(name="cdb_valid")

        # ---- completion / retire ----------------------------------------
        self.cpl_tag = Signal(tag_w, name="cpl_tag")
        self.cpl_valid = Signal(name="cpl_valid")

        # ex operand regs
        self.ex_op_a = Signal(FPR_W, name="ex_op_a")
        self.ex_op_c = Signal(FPR_W, name="ex_op_c")
        self._ex_result = Signal(FPR_W, name="ex_result")
        self._dcd = Decoded()

    def ports(self):
        from amaranth.hdl import IOPort
        return [
            IOPort(32, name="instr"), IOPort(1, name="instr_v"),
            IOPort(self.tag_w, name="cdb_tag"), IOPort(FPR_W, name="cdb_val"),
            IOPort(1, name="cdb_valid"),
            IOPort(self.tag_w, name="cpl_tag"), IOPort(1, name="cpl_valid"),
            IOPort(1, name="stall"), IOPort(1, name="flush_all"),
        ]

    # --- per-stage wiring --------------------------------------------------
    def wire_stage(self, m: Module, i: int, st: Stage, prev):
        d = self._dcd
        if st.name == "disp":
            st.add("instr", 32)
            st.override["instr"] = self.instr

        elif st.name == "rs":
            # decode + rename: allocate a dest tag, snapshot source tags+values
            self._dcd.emit(m, prev.payload["instr"])
            st.add("op", 2); st.add("dt", self.tag_w)
            st.add("at", self.tag_w); st.add("bt", self.tag_w); st.add("ct", self.tag_w)
            st.add("av", FPR_W); st.add("bv", FPR_W); st.add("cv", FPR_W)
            st.add("ar", 1); st.add("br", 1); st.add("cr", 1); st.add("valid", 1)
            st.override["op"] = self._dcd.is_mul
            st.override["valid"] = self._dcd.valid & prev.valid
            # rename: source operand tag = map[arch]; dest gets a fresh tag.
            # v1 simplified: arch==phys index for sources; dest tag = rt index
            # into a small rename pool. Wakeup-ready if the source isn't the
            # target of an in-flight op (tracked per-tag busy).
            for src, t, v, r in (("ra", "at", "av", "ar"),
                                 ("rb", "bt", "bv", "br"),
                                 ("rc", "ct", "cv", "cr")):
                areg = getattr(self._dcd, src)
                avld = getattr(self._dcd, src + "_v")
                tag = self.map[areg.bit_select(0, 6)]
                st.override[t] = tag
                st.override[v] = self.prf[tag]
                # ready if the source isn't a pending producer's dest
                st.override[r] = ~avld | ~self.tag_busy.bit_select(tag, 1)
            st.override["dt"] = self._dcd.rt.bit_select(0, 6)
            # mark the dest tag busy (in-flight producer)
            with m.If(prev.valid & self._dcd.valid & self._dcd.rt_v):
                m.d.sync += self.tag_busy.bit_select(self._dcd.rt.bit_select(0,6),1).eq(1)
                m.d.sync += self.map[self._dcd.rt.bit_select(0,6)].eq(self._dcd.rt.bit_select(0,6))

        elif st.name == "iss":
            # carry the RS entry forward; a CDB broadcast matching a pending
            # src tag fills its value + marks it ready (the wakeup).
            for nm in ("op", "dt", "at", "bt", "ct", "av", "bv", "cv",
                       "ar", "br", "cr", "valid"):
                sig = prev.payload[nm]
                st.add(nm, sig.shape().width)
            for t, v, r in (("at", "av", "ar"), ("bt", "bv", "br"),
                            ("ct", "cv", "cr")):
                ptag = prev.payload[t]
                cdb_hit = ~prev.payload[r] & self.cdb_valid & (self.cdb_tag == ptag)
                st.override[v] = Mux(cdb_hit, self.cdb_val, prev.payload[v])
                st.override[r] = Mux(cdb_hit, Const(1), prev.payload[r])

        elif st.name == "ex":
            for nm in ("op", "dt", "valid"):
                sig = prev.payload[nm]; st.add(nm, sig.shape().width)
            # issue only when all operands ready
            allrdy = prev.payload["ar"] & prev.payload["br"] & prev.payload["cr"]
            m.d.sync += self.ex_op_a.eq(prev.payload["av"])
            m.d.sync += self.ex_op_c.eq(prev.payload["cv"])
            self._build_ex(m, st, prev, allrdy)

        elif st.name == "cdb":
            st.add("dt", self.tag_w); st.add("res", FPR_W); st.add("valid", 1)
            st.override["dt"] = prev.payload["dt"]
            st.override["res"] = self._ex_result
            st.override["valid"] = prev.valid
            m.d.comb += self.cdb_tag.eq(st.payload["dt"])
            m.d.comb += self.cdb_val.eq(st.payload["res"])
            m.d.comb += self.cdb_valid.eq(st.valid)

        elif st.name == "cpl":
            st.add("dt", self.tag_w); st.add("res", FPR_W); st.add("valid", 1)
            st.override["dt"] = prev.payload["dt"]
            st.override["res"] = prev.payload["res"]
            st.override["valid"] = prev.valid
            m.d.comb += self.cpl_tag.eq(st.payload["dt"])
            m.d.comb += self.cpl_valid.eq(st.valid)
            # retire: write PRF, free the tag-busy bit
            with m.If(st.valid):
                m.d.sync += self.prf[st.payload["dt"]].eq(st.payload["res"])
                m.d.sync += self.tag_busy.bit_select(st.payload["dt"], 1).eq(0)

        super().wire_stage(m, i, st, prev)

    def _build_ex(self, m, st, prev, allrdy):
        self._ex = Kernel(self.fu_kernel)
        m.submodules.ex_fu = k = self._ex
        act = getattr(k, "c_ex1_act", None)
        if act is not None:
            m.d.comb += act.eq(st.valid & allrdy & ~st.flush & ~self.stall)
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
        if s is not None and r is not None:
            m.d.comb += self._ex_result.eq(s[:FPR_W] + r[:FPR_W])
