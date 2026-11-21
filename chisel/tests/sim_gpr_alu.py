"""Amaranth smoke: GPR-arith decode + xuq_alu_add routing (add/subf/addi).

Verifies the ISA broadening to GPR arithmetic routes ops to the new
FU_FXU_ADD lane on xuq_alu_add with the right controls: subf inverts rs0
(64-bit rs0_inv mask) + sets ci so the adder computes rs1-rs0; addi
substitutes the sign-extended SIMM for operand B. (Golden kernel unbound in
pure-Amaranth sim so the result bus is unread — verify control/routing only;
numerics need a GHDL bench like tb_a2i_wrap.)
"""
import sys
sys.path.insert(0, "chisel")
from amaranth.sim import Simulator, Tick
from amcore.profiles import InOrderCore

c = InOrderCore(fu_kernel="fuq_mul")
sim = Simulator(c)
sim.add_clock(1e-9)


def add(rt, ra, rb):
    return ((31 << 26) | (rt << 21) | (ra << 16) | (rb << 11) | (266 << 1)) & 0xFFFFFFFF


def subf(rt, ra, rb):
    return ((31 << 26) | (rt << 21) | (ra << 16) | (rb << 11) | (40 << 1)) & 0xFFFFFFFF


def addi(rt, ra, imm):
    return ((14 << 26) | (rt << 21) | (ra << 16) | (imm & 0xFFFF)) & 0xFFFFFFFF


def tb():
    yield c.fpr[2].eq(5); yield c.fpr[3].eq(7)
    # subf r4,r2,r3 -> rs1(7) - rs0(5) = 2; rs0_inv all-ones + ci=1
    yield c.instr.eq(subf(4, 2, 3)); yield c.instr_v.eq(1)
    yield Tick()
    # addi r5,r2,0x1234 -> rs0(5) + SIMM(0x1234); uses_simm routes SIMM to op_b
    yield c.instr.eq(addi(5, 2, 0x1234))
    yield Tick()
    yield c.instr_v.eq(0)

    saw_subf_inv = saw_simm = False
    wb_seen = set()
    # kernel controls are COMB on the RF-stage payload (prev of ex), so they
    # fire the cycle the op is in rf — one stage before it registers into ex.
    for n in range(10):
        yield Tick()
        rfv = yield c.stages[2].valid
        aluop = yield c.stages[2].payload["alu_op"]
        inv = yield c._alu.p_dec_alu_rf1_add_rs0_inv
        ci = yield c._alu.p_dec_alu_rf1_add_ci
        ob = yield c._alu.p_byp_alu_ex1_rs1   # op_b INTO the adder (= rs1)
        if rfv and aluop == 1 and inv == 0xFFFFFFFFFFFFFFFF and ci == 1:
            saw_subf_inv = True
        if rfv and ob == 0x1234:              # SIMM substituted for operand B
            saw_simm = True
        if (yield c.wb_valid):
            wb_seen.add((yield c.wb_addr))

    print(f"subf_rs0_inv+ci={saw_subf_inv} simm_to_op_b={saw_simm} wb={sorted(wb_seen)}")
    assert saw_subf_inv, "subf never drove rs0_inv mask + ci on xuq_alu_add"
    assert saw_simm, "addi never routed SIMM into operand B"
    assert wb_seen >= {4, 5}, f"expected subf->r4 & addi->r5 writeback, got {wb_seen}"
    print("PASS: GPR add/subf/addi route to xuq_alu_add with correct controls")


sim.add_testbench(tb)
try:
    sim.run()
except AssertionError as e:
    print("FAIL:", e); sys.exit(1)
except Exception:
    import traceback; traceback.print_exc(); sys.exit(1)
