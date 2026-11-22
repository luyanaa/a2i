"""Decode-level sim: verify the mul ops decode to FU_FXU_MUL with the right
mul_{ret,size,imm,sign} controls + operand routing (rb for reg-form, simm for
mulli). The kernel's 5-cycle numeric path is verified separately in tb_alumul
(GHDL against golden xuq_alu); this checks the generated decode/control only.

    mullw  (pri31 XO9=235) -> ret=0 size=0 imm=0 sign=1, uses RB
    mulhw  (pri31 XO9=75)  -> ret=1 size=0 imm=0 sign=1
    mulhwu (pri31 XO9=11)  -> ret=1 size=0 imm=0 sign=0
    mulli  (pri 7)         -> ret=0 size=1 imm=1 sign=1, uses SIMM
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from amaranth import Const, Module
from amaranth.sim import Simulator

from amcore.isa.ppc64 import (FU_FXU_MUL, OP_XO, OP_MULLI,
                              XO_MULLW, XO_MULHW, XO_MULHWU,
                              XO_MULLD, XO_MULHD, XO_MULHDU, Decoded)


def enc_xo(rt, ra, rb, xo9, pri=OP_XO, rc=0):
    """Assemble a 32-bit XO-form instruction. xo9 is the 9-bit instr[22:30]
    field (golden mul match); placed at Amaranth bits[1:10] = IBM[22:30]."""
    w = 0
    w |= (pri & 0x3F) << 26          # IBM[0:6]
    w |= (rt & 0x1F) << 21           # IBM[6:11]
    w |= (ra & 0x1F) << 16           # IBM[11:16]
    w |= (rb & 0x1F) << 11           # IBM[16:21]
    w |= (xo9 & 0x1FF) << 1          # IBM[22:31) -> Am bits 1..9
    w |= rc & 1
    return w


def enc_d(pri, rt, ra, simm):
    w = (pri & 0x3F) << 26 | (rt & 0x1F) << 21 | (ra & 0x1F) << 16
    return w | (simm & 0xFFFF)


def main():
    d = Decoded()
    m = Module()
    instr = d._instr if hasattr(d, "_instr") else None
    from amaranth import Signal
    instr = Signal(32, name="instr")
    d.emit(m, instr)

    cases = [
        # (name, instr, exp_ret, exp_size, exp_imm, exp_sign, exp_uses_simm)
        ("mullw",  enc_xo(1, 2, 3, XO_MULLW),  0, 0, 0, 1, 0),
        ("mulhw",  enc_xo(1, 2, 3, XO_MULHW),  1, 0, 0, 1, 0),
        ("mulhwu", enc_xo(1, 2, 3, XO_MULHWU), 1, 0, 0, 0, 0),
        ("mulld",  enc_xo(1, 2, 3, XO_MULLD),  0, 1, 0, 1, 0),
        ("mulhd",  enc_xo(1, 2, 3, XO_MULHD),  1, 1, 0, 1, 0),
        ("mulhdu", enc_xo(1, 2, 3, XO_MULHDU), 1, 1, 0, 0, 0),
        ("mulli",  enc_d(OP_MULLI, 1, 2, 9),   0, 1, 1, 1, 1),
    ]

    sim = Simulator(m)
    results = []

    def proc():
        from amaranth.sim import Settle
        for name, w, er, es, ei, esg, eusi in cases:
            yield instr.eq(w)
            yield Settle()
            v = yield d.valid
            fu = yield d.fu_sel
            mr = yield d.mul_ret
            ms = yield d.mul_size
            mi = yield d.mul_imm
            mg = yield d.mul_sign
            us = yield d.uses_simm
            ok = (v == 1 and fu == FU_FXU_MUL and mr == er and ms == es
                  and mi == ei and mg == esg and us == eusi)
            results.append((name, ok,
                            f"fu={fu} ret={mr} size={ms} imm={mi} sign={mg} simm={us}"))
        for name, ok, info in results:
            print(("PASS" if ok else "FAIL"), name, "->", info)
        assert all(ok for _, ok, _ in results), "mul decode FAIL"

    sim.add_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
