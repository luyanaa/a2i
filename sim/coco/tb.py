# a2x_axi full-core cocotb scaffold bench
# Adapted from ../a2o/dev/sim/coco/tb.py + A2L2.py patterns:
#   - 8ns clk / 4ns clk2x, reset_n held low for a few cycles then released
#   - thold='0' (tri latches act as ordinary rising-edge registers)
#   - AXI slave over the m00_axi_* ports (a2l2_axi is the master)
#   - sparse word-addressed memory (dict), preloaded with a tiny program
#     at the A2I reset PC (0xFFFFFFFC) and a magic-address store
#   - pass/fail via magic-address write detection (A2O.PASS/FAIL addrs)
#
# Scaffold goal (NOT full instruction verification): the core resets,
# starts fetching through the A2L2->AXI bridge, and completes at least one
# full AXI read transaction.

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer, First

CFG = {
    "C_M00_AXI_ID_WIDTH": 4,
    "C_M00_AXI_ADDR_WIDTH": 32,
    "C_M00_AXI_DATA_WIDTH": 32,
}

# A2I reset PC and standard self-loop op (from a2o OPEnv: resetAddr/Op)
RESET_PC = 0xFFFFFFFC
RESET_OP = 0x48000002        # branch to self
MAGIC_PASS = 0x2004          # a2o convention: store here = pass
MAGIC_FAIL = 0x2000          # store here = fail

MAX_CYCLES = int(os.environ.get("A2X_MAX_CYCLES", 20000))


class MemModel:
    """Sparse word (32b) memory keyed by word address."""

    def __init__(self, words=None):
        self.mem = {} if words is None else dict(words)

    def read(self, addr):
        return self.mem.get(addr & ~0, 0) & 0xFFFFFFFF

    def write(self, addr, data):
        self.mem[addr & ~0] = data & 0xFFFFFFFF


def build_program():
    """Tiny program: reset PC self-loop, nops, and a magic PASS store.

    The core starts fetching at RESET_PC; nothing here claims the core
    executes to the store — the scaffold asserts AXI activity, and a magic
    write (if it ever happens) is reported as a bonus pass signal.
    """
    words = {
        RESET_PC: RESET_OP,
        0xFFFFFF00: 0x60000000,          # nop
        0xFFFFFF04: 0x60000000,          # nop
        0xFFFFFF08: 0x9421FFC0,          # stwu r1,-64(r1)
        0xFFFFFF0C: 0x3C602000,          # lis r3,0x2000
        0xFFFFFF10: 0x90630004,          # stw r3,4(r3)  -> MAGIC_PASS store
        0xFFFFFF14: 0x48000002,          # branch to self
    }
    return {a >> 2: d for a, d in words.items()}   # word addresses


class AxiSlave:
    """Minimal AXI4-Lite-ish slave on the m00_axi_* master signals.

    Accepts single/burst transactions. Reads stream back arlen+1 beats with
    incrementing word address; writes accept AW+W and return OKAY B.
    """

    def __init__(self, dut, mem: MemModel):
        self.dut = dut
        self.mem = mem
        self.transactions = 0
        self.reads = 0
        self.writes = 0

    async def run(self):
        c = self.dut
        # inputs
        c.m00_axi_awready.value = 0
        c.m00_axi_wready.value = 0
        c.m00_axi_bvalid.value = 0
        c.m00_axi_bid.value = 0
        c.m00_axi_bresp.value = 0
        c.m00_axi_rvalid.value = 0
        c.m00_axi_rid.value = 0
        c.m00_axi_rdata.value = 0
        c.m00_axi_rresp.value = 0
        c.m00_axi_rlast.value = 0

        aw_pending = None
        b_pending = False
        read_beats = []

        for _ in range(MAX_CYCLES):
            await RisingEdge(c.clk)
            # --- read address ---
            if c.m00_axi_arvalid.value == 1 and c.m00_axi_arready.value == 1:
                addr = int(c.m00_axi_araddr.value) & 0xFFFFFFFC
                try:
                    arlen = int(c.m00_axi_arlen.value)
                except ValueError:
                    arlen = 0
                nbeats = arlen + 1
                self.transactions += 1
                self.reads += 1
                self.dut._log.info(
                    f"[axi] AR: addr=0x{addr:08X} len={arlen} beats={nbeats}")
                read_beats = [
                    self.mem.read((addr >> 2) + i) for i in range(nbeats)
                ]
                c.m00_axi_rvalid.value = 1
                c.m00_axi_rdata.value = read_beats[0]
                c.m00_axi_rlast.value = 1 if len(read_beats) == 1 else 0

            # --- read data handshakes ---
            if c.m00_axi_rvalid.value == 1 and c.m00_axi_rready.value == 1:
                if read_beats:
                    read_beats.pop(0)
                if read_beats:
                    c.m00_axi_rdata.value = read_beats[0]
                    c.m00_axi_rlast.value = 1 if len(read_beats) == 1 else 0
                else:
                    c.m00_axi_rvalid.value = 0
                    c.m00_axi_rlast.value = 0

            # --- write address ---
            if aw_pending is None and c.m00_axi_awvalid.value == 1:
                addr = int(c.m00_axi_awaddr.value) & 0xFFFFFFFC
                try:
                    awlen = int(c.m00_axi_awlen.value)
                except ValueError:
                    awlen = 0
                self.transactions += 1
                self.writes += 1
                self.dut._log.info(
                    f"[axi] AW: addr=0x{addr:08X} len={awlen} -> wready")
                aw_pending = addr
                c.m00_axi_awready.value = 1

            if c.m00_axi_awready.value == 1 and c.m00_axi_awvalid.value == 1:
                c.m00_axi_awready.value = 0

            # --- write data ---
            if aw_pending is not None and c.m00_axi_wvalid.value == 1:
                try:
                    data = int(c.m00_axi_wdata.value) & 0xFFFFFFFF
                    strb = int(c.m00_axi_wstrb.value)
                except ValueError:
                    data, strb = 0, 0
                addr = aw_pending
                old = self.mem.read(addr >> 2)
                new = old
                for byte in range(4):
                    if (strb >> byte) & 1:
                        new &= ~(0xFF << (8 * byte))
                        new |= (data & (0xFF << (8 * byte)))
                self.mem.write(addr >> 2, new)
                self.dut._log.info(
                    f"[axi] W: addr=0x{addr:08X} data=0x{data:08X} strb=0x{strb:X}")
                self.check_magic(addr, new)
                aw_pending = False
                c.m00_axi_wready.value = 1
                b_pending = True
                c.m00_axi_bvalid.value = 1

            if c.m00_axi_wready.value == 1 and c.m00_axi_wvalid.value == 1:
                c.m00_axi_wready.value = 0

            # --- write response ---
            if b_pending and c.m00_axi_bready.value == 1:
                c.m00_axi_bvalid.value = 0
                b_pending = False

    def check_magic(self, addr, new):
        if addr >> 2 == MAGIC_PASS >> 2:
            self.dut._log.info(f"[axi] *** MAGIC PASS WRITE: 0x{new:08X} ***")
        elif addr >> 2 == MAGIC_FAIL >> 2:
            self.dut._log.info(f"[axi] *** MAGIC FAIL WRITE: 0x{new:08X} ***")


async def reset(dut, cycles=5):
    """reset_n low for `cycles` clk periods, thold=0, then release."""
    dut.thold.value = 0
    dut.reset_n.value = 0
    # initialize all misc inputs (a2x_axi ties most of them internally)
    dut.core_id.value = 0
    dut.thread_stop.value = 0xF          # threads stopped until we release
    dut.ext_mchk.value = 0
    dut.ext_checkstop.value = 0
    dut.debug_stop.value = 0
    dut.crit_interrupt.value = 0
    dut.ext_interrupt.value = 0
    dut.perf_interrupt.value = 0
    dut.tb_update_enable.value = 1
    dut.tb_update_pulse.value = 0
    dut.scom_sat_id.value = 0
    dut.scom_dch_in.value = 0
    dut.scom_cch_in.value = 0
    dut.flh2l2_gate.value = 0
    dut.hang_pulse.value = 0
    await Timer(8, units="ns")
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.reset_n.value = 1
    dut.thread_stop.value = 0            # release threads
    dut._log.info("[tb] reset released, threads running")


@cocotb.test()
async def tb_a2x_axi_reset_and_axi(dut):
    """Full-core scaffold: clocks + reset + first AXI fetch transaction."""
    # clocks: 8ns clk, 4ns clk2x (2x clk, phase aligned)
    cocotb.start_soon(Clock(dut.clk, 8, units="ns").start())
    cocotb.start_soon(Clock(dut.clk2x, 4, units="ns").start())

    mem = MemModel(build_program())
    slave = AxiSlave(dut, mem)
    slave_task = cocotb.start_soon(slave.run())
    reset_task = cocotb.start_soon(reset(dut))

    # Scaffold success criterion: at least one AXI AR (fetch) transaction
    # completes within MAX_CYCLES of reset release.
    timeout = Timer(MAX_CYCLES * 8, units="ns")
    while slave.transactions == 0:
        if await First(Timer(8, units="ns"), timeout) == timeout:
            slave_task.cancel()
            dut._log.error(
                f"[tb] TIMEOUT: no AXI transaction after {MAX_CYCLES} cycles "
                f"(reset completed, core did not fetch)")
            raise AssertionError("no AXI fetch transaction seen")
    # let the read burst play out
    for _ in range(64):
        await RisingEdge(dut.clk)
        if slave.reads > 0 and len(slave.mem) and slave.writes >= 0:
            break
    slave_task.cancel()
    dut._log.info(
        f"[tb] PASS: {slave.transactions} AXI transaction(s), "
        f"{slave.reads} read(s), {slave.writes} write(s)")
    assert slave.reads >= 1
