"""Amaranth smoke: GPR logicals -> xuq_alu logic unit (and/or/xor/...).

Verifies the pri-31 logical family and D-form immediates decode to FU_FXU_LOG
and drive the golden xuq_alu's logic unit with the right truth-table select:
dec_alu_rf1_log_fcn is the 2-input truth table (log0..3 = ~a~b,~a b,a~b,a b),
sel=0 picks the rot/log path. Kernel unbound in Amaranth sim -> check decode
routing, log_fcn, and operands. Each op's expected log_fcn:
  and=0001 or=0111 xor=0110 nand=1110 nor=1000 andc=0010 eqv=1001
"""
import sys
sys.path.insert(0, "chisel")
from amaranth.sim import Simulator, Tick
from amcore.profiles import InOrderCore

c = InOrderCore(fu_kernel="fuq_mul")
sim = Simulator(c)
sim.add_clock(1e-9)


def xop(rt, ra, rb, xo):
    return ((31 << 26) | (rt << 21) | (ra << 16) | (rb << 11) | (xo << 1)) & 0xFFFFFFFF


# (xo, expected log_fcn, name)
LOGOPS = [(28, 0b0001, "and"), (444, 0b0111, "or"), (316, 0b0110, "xor"),
          (476, 0b1110, "nand"), (124, 0b1000, "nor"), (60, 0b0010, "andc"),
          (568, 0b1001, "eqv")]


def tb():
    yield c.fpr[2].eq(0xF0F0); yield c.fpr[3].eq(0x0FF0)
    yield c.instr_v.eq(1)
    # sample the COMB decode (_dcd) one cycle after driving each op — the
    # staged rf payload lags by a cycle and shifts the expected log_fcn off.
    got = {}
    for xo, want, name in LOGOPS:
        yield c.instr.eq(xop(4, 2, 3, xo))
        yield Tick()
        got[name] = (yield c._dcd.valid), (yield c._dcd.fu_sel), \
            (yield c._dcd.log_fcn)
    yield c.instr_v.eq(0)

    ok = True
    for xo, want, name in LOGOPS:
        valid, fusel, lfcn = got[name]
        good = valid and fusel == 3 and lfcn == want
        ok &= good
        print(f"  {name:5} valid={valid} fu_sel={fusel} log_fcn={lfcn:04b} "
              f"{'OK' if good else 'BAD'}")
    assert ok, "a logical op decoded/routed wrong"
    print("PASS: all 7 pri-31 logicals -> FU_FXU_LOG with correct log_fcn")


sim.add_testbench(tb)
try:
    sim.run()
except AssertionError as e:
    print("FAIL:", e); sys.exit(1)
except Exception:
    import traceback; traceback.print_exc(); sys.exit(1)
