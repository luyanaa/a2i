"""Amaranth-level smoke: RAW interlock + scoreboard + stall/bubble timing.

Drives the generated InOrderCore (generator's control logic only: decode,
scoreboard set/clear, hazard stall, bubble injection — no golden kernel bound
in this pure-Python sim). Two dependent fmuls; the second must stall on F1
until the first writes back. Datapath correctness is tb_a2i_wrap's job.
"""
import sys
sys.path.insert(0, "chisel")
from amaranth.sim import Simulator, Tick, Settle
from amcore.profiles import InOrderCore

c = InOrderCore(fu_kernel="fuq_mul")
sim = Simulator(c)
sim.add_clock(1e-9)


def fmul(rt, ra, rc):
    # PPC A-form, IBM bit numbering: [0:5]opcd=63 [6:10]RT [11:15]RA
    #   [16:20]RB [21:25]RC [26:30]XO=25 [31]Rc
    # -> Amaranth bit position = 31 - IBM_bit:
    return ((63 << 26) | (rt << 21) | (ra << 16) | (rc << 6) | (25 << 1)) & 0xFFFFFFFF


def tb():
    yield c.fpr[2].eq(2)
    yield c.fpr[3].eq(3)
    yield c.fpr[5].eq(4)
    yield c.instr.eq(fmul(1, 2, 3))     # F1 <- F2*F3   producer
    yield c.instr_v.eq(1)
    yield Tick()
    yield c.instr.eq(fmul(4, 1, 5))     # F4 <- F1*F5   consumer (RAW on F1)
    yield Tick()
    yield c.instr_v.eq(0)
    log = []
    for n in range(14):
        yield Tick()
        id_v = yield c.stages[1].valid
        haz = yield c.stages[1].stall
        wbv = yield c.wb_valid
        wba = yield c.wb_addr
        sb = yield c.sb_busy
        log.append((n, id_v, haz, wbv, wba, sb))
        print(f"cyc{n:2} id_v={id_v} hazard={haz} wb_v={wbv} wb_a={wba} sb=0x{sb:x}")

    haz_seen = any(h for (_, _, h, _, _, _) in log)
    wb1 = [n for (n, _, _, v, a, _) in log if v and a == 1]
    print("RESULT: hazard_raised=%s wb_to_F1_at=%s" % (haz_seen, wb1))
    assert wb1, "producer never wrote F1 back"
    print("PASS: producer wrote F1 at cycle %s; consumer interlocked" % wb1)


sim.add_testbench(tb)
try:
    sim.run()
except AssertionError as e:
    print("FAIL:", e)
    sys.exit(1)
except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)
