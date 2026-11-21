"""Amaranth smoke: the bypsel forward — a dependent op completes WITHOUT
stalling because its source is forwarded from EX/WB instead of waiting on the
FPR writeback.

Two fmuls, the second RAW-dependent on the first's FRT. With the forward,
the consumer reads the producer's result combinationally at RF (hit_ex or
hit_wb) rather than a stale FPR value — no scoreboard stall. (Golden kernel
is unbound in pure-Amaranth sim so wb_data is 0; what we verify is the
*control*: forward-select fires, no stall, both ops reach wb.)
"""
import sys
sys.path.insert(0, "chisel")
from amaranth.sim import Simulator, Tick
from amcore.profiles import InOrderCore

c = InOrderCore(fu_kernel="fuq_mul")
sim = Simulator(c)
sim.add_clock(1e-9)


def fmul(rt, ra, rc):
    return ((63 << 26) | (rt << 21) | (ra << 16) | (rc << 6) | (25 << 1)) & 0xFFFFFFFF


def tb():
    yield c.fpr[2].eq(0x1111)
    yield c.fpr[3].eq(0x2222)
    yield c.fpr[5].eq(0x3333)
    yield c.instr.eq(fmul(1, 2, 3))     # F1 <- F2*F3  producer
    yield c.instr_v.eq(1)
    yield Tick()
    yield c.instr.eq(fmul(4, 1, 5))     # F4 <- F1*F5  consumer, RAW on F1
    yield Tick()
    yield c.instr_v.eq(0)

    fwd_hit = False
    nstall = 0
    wb_seen = set()
    for n in range(8):
        yield Tick()
        haz = yield c.stages[1].stall
        wba = yield c.wb_addr
        wbv = yield c.wb_valid
        pex_rtv = yield c.prod_ex_rtv
        pex_rt = yield c.prod_ex_rt
        rf_ra = yield c.stages[2].payload["ra"]
        # producer F1 live+forwardable in EX while consumer reads rf_ra=1
        if pex_rtv and pex_rt == 1 and rf_ra == 1:
            fwd_hit = True
        nstall += haz
        if wbv:
            wb_seen.add(wba)

    print(f"fwd_hit(F1 in EX while consumer reads ra=1)={fwd_hit} "
          f"stalls={nstall} wb_written={sorted(wb_seen)}")
    assert nstall == 0, f"consumer stalled {nstall}x despite bypass"
    assert fwd_hit, "producer never appeared forwardable in EX"
    assert wb_seen == {1, 4}, f"expected wb to F1,F4; got {wb_seen}"
    print("PASS: dependent fmul forwarded without stall (bypsel network live)")


sim.add_testbench(tb)
try:
    sim.run()
except AssertionError as e:
    print("FAIL:", e); sys.exit(1)
except Exception:
    import traceback; traceback.print_exc(); sys.exit(1)
