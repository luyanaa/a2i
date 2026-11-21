"""Amaranth smoke: D-form load/store -> xuq_agen effective-address lane.

Verifies lwz/stw decode to FU_AGEN and drive the golden xuq_agen's EA adder:
x <- RA base register, y <- sign-extended SIMM displacement, mode64=1. The
kernel is an unbound blackbox in pure-Amaranth sim (sum outputs read 0); the
check is decode routing + operand substitution + writeback target. EA
numerics need a GHDL bench (tb_a2i_wrap pattern).
"""
import sys
sys.path.insert(0, "chisel")
from amaranth.sim import Simulator, Tick
from amcore.profiles import InOrderCore

c = InOrderCore(fu_kernel="fuq_mul")
sim = Simulator(c)
sim.add_clock(1e-9)


def lwz(rt, ra, d):
    return ((32 << 26) | (rt << 21) | (ra << 16) | (d & 0xFFFF)) & 0xFFFFFFFF


def stw(rt, ra, d):
    return ((36 << 26) | (rt << 21) | (ra << 16) | (d & 0xFFFF)) & 0xFFFFFFFF


def tb():
    yield c.fpr[2].eq(0x1000)   # RA base
    yield c.fpr[7].eq(0xDEAD)   # RT store data
    yield c.instr.eq(lwz(4, 2, 0x80))   # EA = 0x1000 + 0x80 -> load into r4
    yield c.instr_v.eq(1)
    yield Tick()
    yield c.instr.eq(stw(7, 2, 0x40))   # EA = 0x1000 + 0x40 -> store r7
    yield Tick()
    yield c.instr_v.eq(0)

    agen_ops = []
    wb_seen = set()
    # operands x/y are registered into ex (ex_op_a / op_b mux), so sample the
    # agen inputs the cycle the op sits in EX (stages[3]), when both are valid.
    for n in range(10):
        yield Tick()
        exv = yield c.stages[3].valid
        fusel = yield c.stages[3].payload["fu_sel"]
        gx = yield c._agen.p_x
        gy = yield c._agen.p_y
        m64 = yield c._agen.p_mode64
        if exv and fusel == 2:          # FU_AGEN, in EX with real operands
            agen_ops.append((gx, gy, m64))
        if (yield c.wb_valid):
            wb_seen.add((yield c.wb_addr))

    print(f"agen_ops(x,y,m64)={agen_ops} wb={sorted(wb_seen)}")
    # lwz: EA=0x1000+0x80 -> writes r4. stw: EA=0x1000+0x40 (no wb).
    assert (0x1000, 0x80, 1) in agen_ops, "lwz EA operands not routed to agen"
    assert (0x1000, 0x40, 1) in agen_ops, "stw EA operands not routed to agen"
    assert 4 in wb_seen, f"lwz never wrote back r4, got {wb_seen}"
    print("PASS: lwz/stw route RA+SIMM to xuq_agen; lwz writes its RT")


sim.add_testbench(tb)
try:
    sim.run()
except AssertionError as e:
    print("FAIL:", e); sys.exit(1)
except Exception:
    import traceback; traceback.print_exc(); sys.exit(1)
