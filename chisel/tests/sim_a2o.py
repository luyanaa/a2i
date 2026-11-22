"""Amaranth smoke: a2o OoO skeleton — decode+rename, tag wakeup, CDB, retire.

Producer fmul -> tag for F1; consumer fmul's source F1 is tag-busy so it
waits in the reservation station until the producer's CDB broadcast wakes it.
Then it issues, broadcasts its own result, and retires in order. Verifies the
OoO control path (rename tag, operand-ready wakeup via CDB, completion) is
live over the same decode+kernel the in-order profile uses.
"""
import sys
sys.path.insert(0, "chisel")
from amaranth.sim import Simulator, Tick
from amcore.profiles import OoOCore

c = OoOCore(fu_kernel="fuq_mul")
sim = Simulator(c)
sim.add_clock(1e-9)


def fmul(rt, ra, rc):
    return ((63 << 26) | (rt << 21) | (ra << 16) | (rc << 6) | (25 << 1)) & 0xFFFFFFFF


def tb():
    yield c.prf[2].eq(0xAAAA); yield c.prf[3].eq(0xBBBB); yield c.prf[5].eq(0xCCCC)
    yield c.map[2].eq(2); yield c.map[3].eq(3); yield c.map[5].eq(5)
    yield c.instr.eq(fmul(1, 2, 3))     # producer -> F1
    yield c.instr_v.eq(1)
    yield Tick()
    yield c.instr.eq(fmul(4, 1, 5))     # consumer -> F4, src F1 (RAW)
    yield Tick()
    yield c.instr_v.eq(0)

    cdb_of_tag1 = False
    cpl_order = []
    for n in range(12):
        yield Tick()
        if (yield c.cdb_valid) and (yield c.cdb_tag) == 1:
            cdb_of_tag1 = True
        if (yield c.cpl_valid):
            cpl_order.append((yield c.cpl_tag))

    cpl_order = list(dict.fromkeys(cpl_order))  # dedupe consecutive
    print(f"cdb_broadcast_tag1={cdb_of_tag1} cpl_order={cpl_order}")
    assert cdb_of_tag1, "producer never broadcast its result on the CDB"
    assert cpl_order and cpl_order[0] == 1 and 4 in cpl_order, \
        f"expected in-order retire of tag1 then tag4, got {cpl_order}"
    print("PASS: OoO decode+rename+wakeup+CDB+in-order retire over shared kernel")


sim.add_testbench(tb)
try:
    sim.run()
except AssertionError as e:
    print("FAIL:", e); sys.exit(1)
except Exception:
    import traceback; traceback.print_exc(); sys.exit(1)
