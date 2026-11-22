"""Decode-level sim: verify the div ops decode to FU_FXU_DIV with the right
div_{sign,size,extd,ctr} controls + operand routing. The kernel's iterative
numeric path is verified separately in tb_aludiv (GHDL against golden xuq_alu);
this checks the generated decode/control only.

    divw   (pri31 XO9=491) -> sign=1 size=0 extd=0 ctr=33
    divwu  (pri31 XO9=459) -> sign=0 size=0 extd=0 ctr=33
    divd   (pri31 XO9=489) -> sign=1 size=1 extd=0 ctr=65
    divdu  (pri31 XO9=457) -> sign=0 size=1 extd=0 ctr=65
    divwe  (pri31 XO9=427) -> sign=1 size=0 extd=1 ctr=65
    divde  (pri31 XO9=201) -> sign=1 size=1 extd=1 ctr=129
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from amaranth import Module, Signal
from amaranth.sim import Simulator

from amcore.isa.ppc64 import (FU_FXU_DIV, OP_XO,
                              XO_DIVW, XO_DIVWU, XO_DIVD, XO_DIVDU,
                              XO_DIVWE, XO_DIVDE, Decoded)


def enc_xo(rt, ra, rb, xo9, pri=OP_XO, rc=0):
    w = (pri & 0x3F) << 26 | (rt & 0x1F) << 21 | (ra & 0x1F) << 16 \
        | (rb & 0x1F) << 11 | (xo9 & 0x1FF) << 1 | (rc & 1)
    return w


def main():
    d = Decoded()
    m = Module()
    instr = Signal(32, name="instr")
    d.emit(m, instr)

    cases = [
        # (name, instr, exp_sign, exp_size, exp_extd, exp_ctr)
        ("divw",  enc_xo(1, 2, 3, XO_DIVW),  1, 0, 0, 33),
        ("divwu", enc_xo(1, 2, 3, XO_DIVWU), 0, 0, 0, 33),
        ("divd",  enc_xo(1, 2, 3, XO_DIVD),  1, 1, 0, 65),
        ("divdu", enc_xo(1, 2, 3, XO_DIVDU), 0, 1, 0, 65),
        ("divwe", enc_xo(1, 2, 3, XO_DIVWE), 1, 0, 1, 65),
        ("divde", enc_xo(1, 2, 3, XO_DIVDE), 1, 1, 1, 129),
    ]

    sim = Simulator(m)
    results = []

    def proc():
        from amaranth.sim import Settle
        for name, w, esg, esz, eex, ectr in cases:
            yield instr.eq(w)
            yield Settle()
            v = yield d.valid
            fu = yield d.fu_sel
            sg = yield d.div_sign
            sz = yield d.div_size
            ex = yield d.div_extd
            ct = yield d.div_ctr
            ok = (v == 1 and fu == FU_FXU_DIV and sg == esg and sz == esz
                  and ex == eex and ct == ectr)
            results.append((name, ok,
                            f"fu={fu} sign={sg} size={sz} extd={ex} ctr={ct}"))
        for name, ok, info in results:
            print(("PASS" if ok else "FAIL"), name, "->", info)
        assert all(ok for _, ok, _ in results), "div decode FAIL"

    sim.add_process(proc)
    sim.run()


if __name__ == "__main__":
    main()
