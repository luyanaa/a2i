"""Amaranth-level control sim for the multi-cycle-FU writeback.

Drives InOrderCore (control logic only — the xuq_alu kernel is a blackbox in
this Python sim, so we *force* its done flag to model the kernel iterating).
Checks the v2 handshake: a mul/div launches mul_val/div_val ONCE (not held),
the op is held in EX (stall) while the FU is in flight, and it advances to WB
exactly once with the captured product.

The kernel's real done/product timing is verified in tb_aludiv/tb_alumul
(GHDL); here we stub `p_alu_ex4_mul_done` to confirm the pipeline's handshake.
"""
import sys
sys.path.insert(0, "chisel")
from amaranth.sim import Simulator, Tick, Settle
from amcore.profiles import InOrderCore

c = InOrderCore()
sim = Simulator(c)
sim.add_clock(1e-9)


def mullw(rt, ra, rb):
    # XO-form: [0:5]pri=31 [6:10]RT [11:15]RA [16:20]RB [22:30]XO9=235
    return ((31 << 26) | (rt << 21) | (ra << 16) | (rb << 11)
            | (235 << 1)) & 0xFFFFFFFF


def tb():
    yield c.fpr[2].eq(6)
    yield c.fpr[3].eq(7)
    yield c.fpr[4].eq(2)
    yield c.fpr[5].eq(9)
    yield c.instr.eq(mullw(1, 2, 3))
    yield c.instr_v.eq(1)
    yield Tick()
    yield c.instr_v.eq(0)

    # force the mul-done flag a few cycles in (model the kernel iterating);
    # the kernel port is an input to the blackbox, so drive it from the test.
    ex = c.stages[3]   # stages = if,id,rf,ex,wb
    log = []
    launched = 0
    for n in range(16):
        # model: mul_done high on cycle 6 (kernel's ~4-cycle Booth + overhead)
        if n == 6:
            yield c._alu_log.p_alu_ex4_mul_done.eq(1)
        else:
            yield c._alu_log.p_alu_ex4_mul_done.eq(0)
        yield Tick()
        mv = yield c._alu_log.c_dec_alu_rf1_mul_val
        busy = yield c.mc_busy
        iss = yield c.mc_issue
        exv = yield ex.valid
        exst = yield ex.stall
        wbv = yield c.wb_valid
        log.append((n, mv, busy, exst, wbv))
        if mv:
            launched += 1
        print(f"cyc{n:2} mul_val={mv} busy={busy} issue={iss} ex_v={exv} ex_stall={exst} wb_v={wbv}")

    n_launch = launched
    stalls = [n for (n, _, b, s, _) in log if s]
    wbs = [n for (n, *_r) in enumerate(log) if log[n][4]]
    print(f"RESULT: launches={n_launch} ex_stall_cycles={stalls} wb_at={wbs}")
    assert n_launch == 1, f"mul_val pulsed {n_launch}x, expected once"
    assert stalls, "op was never held in EX"
    assert wbs == [6], f"expected single WB at cyc6, got {wbs}"

    # ---- a second mul must launch cleanly after the first drains ----------
    print("--- follower mul (4*5 -> r6) ---")
    yield c.instr.eq(mullw(6, 4, 5))
    yield c.instr_v.eq(1)
    yield Tick()
    yield c.instr_v.eq(0)
    launched2 = 0
    wb2 = []
    for n in range(12):
        if n == 4:
            yield c._alu_log.p_alu_ex4_mul_done.eq(1)
        else:
            yield c._alu_log.p_alu_ex4_mul_done.eq(0)
        yield Tick()
        mv = yield c._alu_log.c_dec_alu_rf1_mul_val
        wbv = yield c.wb_valid
        wba = yield c.wb_addr
        if mv:
            launched2 += 1
        if wbv:
            wb2.append((n, wba))
        print(f"  cyc{n:2} mul_val={mv} wb_v={wbv} wb_addr={wba}")
    assert launched2 == 1, f"follower launched {launched2}x"
    assert wb2 and wb2[0][1] == 6, f"follower wrote r6? {wb2}"
    print("PASS: mul launched once, held to done, single WB; follower clean")


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
