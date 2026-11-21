#!/usr/bin/env python3
"""Generate sim-shadow sources for the a2x_axi cocotb harness.

Two derived artifacts, frozen originals in /shared/a2i/rel are never touched:

1. sim_shadow/{ibm,clib,support,tri}/*.vhdl — copies of the frozen libraries
   with the 217 synthesis-only `pin_bit_information` attribute *specifications*
   stripped (they trip GHDL elaboration; the pbi_t type decl stays so
   downstream references resolve). Same philosophy as tools/run.py.

2. unimacro_sim/bram_tdp_macro_sim.vhdl — the entity-only
   /shared/a2i/rel/sim/unimacro/bram_tdp_macro_mock.vhdl plus a behavioral
   dual-port RAM architecture with INIT_xx preload, so BRAM-based array
   units (tri ramb16_* wrappers) actually store/read data in simulation.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]             # worktree root
A2I = Path('/shared/a2i/rel')
SRC = A2I / "src" / "vhdl"
OUT = Path(__file__).resolve().parent / "sim_shadow"

PBI = re.compile(r"attribute\s+pin_bit_information\s+of\s+[^;]+;", re.I | re.S)


def shadow(lib: str):
    out = OUT / lib
    out.mkdir(parents=True, exist_ok=True)
    for f in sorted((SRC / lib).glob("*.vhdl")):
        txt = f.read_text()
        new = PBI.sub(lambda m: "-- [sim-shadow] " + m.group(0).replace("\n", "\n-- "), txt)
        (out / f.name).write_text(new)
    print(f"shadow: {lib} -> {out}")


BRAM_ARCH = r"""

-- =========================================================================
-- [sim-shadow] Behavioral architecture appended for cocotb simulation.
-- True dual-port synchronous RAM; depth = 2**ADDRA'length, word width =
-- DIA'length, WEA bit-per-lane byte enables (lane = width/lanes).
-- INIT_00..INIT_7F are preloaded as a Xilinx-style little-endian bit stream:
-- bit j of INIT_xx (hex string, bit 0 = LSB) fills bit j of the concatenated
-- stream; word w occupies bits [w*width +: width] of that stream.
-- Ports are unconstrained and may be connected with downto ranges, so all
-- accesses go through normalized downto locals.
-- =========================================================================
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

architecture sim of BRAM_TDP_MACRO is

  type t_init_vec is array (natural range <>) of bit_vector;
  constant INIT_VEC : t_init_vec(0 to 127) := (
    INIT_00,
    INIT_01,
    INIT_02,
    INIT_03,
    INIT_04,
    INIT_05,
    INIT_06,
    INIT_07,
    INIT_08,
    INIT_09,
    INIT_0A,
    INIT_0B,
    INIT_0C,
    INIT_0D,
    INIT_0E,
    INIT_0F,
    INIT_10,
    INIT_11,
    INIT_12,
    INIT_13,
    INIT_14,
    INIT_15,
    INIT_16,
    INIT_17,
    INIT_18,
    INIT_19,
    INIT_1A,
    INIT_1B,
    INIT_1C,
    INIT_1D,
    INIT_1E,
    INIT_1F,
    INIT_20,
    INIT_21,
    INIT_22,
    INIT_23,
    INIT_24,
    INIT_25,
    INIT_26,
    INIT_27,
    INIT_28,
    INIT_29,
    INIT_2A,
    INIT_2B,
    INIT_2C,
    INIT_2D,
    INIT_2E,
    INIT_2F,
    INIT_30,
    INIT_31,
    INIT_32,
    INIT_33,
    INIT_34,
    INIT_35,
    INIT_36,
    INIT_37,
    INIT_38,
    INIT_39,
    INIT_3A,
    INIT_3B,
    INIT_3C,
    INIT_3D,
    INIT_3E,
    INIT_3F,
    INIT_40,
    INIT_41,
    INIT_42,
    INIT_43,
    INIT_44,
    INIT_45,
    INIT_46,
    INIT_47,
    INIT_48,
    INIT_49,
    INIT_4A,
    INIT_4B,
    INIT_4C,
    INIT_4D,
    INIT_4E,
    INIT_4F,
    INIT_50,
    INIT_51,
    INIT_52,
    INIT_53,
    INIT_54,
    INIT_55,
    INIT_56,
    INIT_57,
    INIT_58,
    INIT_59,
    INIT_5A,
    INIT_5B,
    INIT_5C,
    INIT_5D,
    INIT_5E,
    INIT_5F,
    INIT_60,
    INIT_61,
    INIT_62,
    INIT_63,
    INIT_64,
    INIT_65,
    INIT_66,
    INIT_67,
    INIT_68,
    INIT_69,
    INIT_6A,
    INIT_6B,
    INIT_6C,
    INIT_6D,
    INIT_6E,
    INIT_6F,
    INIT_70,
    INIT_71,
    INIT_72,
    INIT_73,
    INIT_74,
    INIT_75,
    INIT_76,
    INIT_77,
    INIT_78,
    INIT_79,
    INIT_7A,
    INIT_7B,
    INIT_7C,
    INIT_7D,
    INIT_7E,
    INIT_7F
  );

  constant DEPTH : natural := 2 ** ADDRA'length;
  constant WW    : natural := DIA'length;   -- word width
  constant LANES : natural := WEA'length;   -- write-enable lanes
  constant LANE  : natural := WW / LANES;   -- bits per lane

  type mem_t is array (0 to DEPTH - 1) of std_logic_vector(WW - 1 downto 0);
  shared variable mem : mem_t := (others => (others => '0'));

  -- normalized access helpers
  function to_dn(v : std_logic_vector) return std_logic_vector is
    variable r : std_logic_vector(v'length - 1 downto 0);
  begin
    for i in v'range loop r(i - v'low) := v(i); end loop;
    return r;
  end function;

begin

  -- preload INIT_xx contents (Xilinx little-endian bit packing)
  preload : process
    variable acc : std_logic_vector(0 to 128 * 256 - 1) := (others => '0');
    variable bv  : std_logic_vector(0 to 255);
    -- INIT_xx packs 128*256 bits covering the full macro; the usable word
    -- count is the *physical* depth, not packed_bits/WW (which overshoots
    -- DEPTH whenever WW doesn't tile the region evenly, e.g. WW=9, DEPTH=2048:
    -- 128*256/9 = 3640 > 2048). Clamp to the smaller of the two.
    constant WORDS : natural := minimum(128 * 256 / WW, DEPTH);
  begin
    for c in 0 to 127 loop
      -- note: cannot index INIT_xx by name in a loop, so the values are
      -- patched in at elaboration by the generated constant INIT_VEC below.
      bv := ieee.std_logic_1164.to_stdlogicvector(INIT_VEC(c));
      for j in 0 to 255 loop
        acc(c * 256 + j) := bv(255 - j);
      end loop;
    end loop;
    for a in 0 to WORDS - 1 loop
      for b in 0 to WW - 1 loop
        if a * WW + b <= acc'high then
          mem(a)(b) := acc(a * WW + b);
        end if;
      end loop;
    end loop;
    wait;
  end process;

  port_a : process (CLKA)
    variable ad : natural range 0 to DEPTH - 1;
    variable di : std_logic_vector(WW - 1 downto 0);
    variable we : std_logic_vector(LANES - 1 downto 0);
  begin
    if rising_edge(CLKA) then
      ad := to_integer(unsigned(to_dn(ADDRA)));
      for i in DIA'range loop di(i - DIA'low) := DIA(i); end loop;
      for i in WEA'range loop we(i - WEA'low) := WEA(i); end loop;
      if ENA = '1' then
        if RSTA = '1' then
          for i in DOA'range loop
            DOA(i) <= to_stdlogicvector(SRVAL_A)(i - DOA'low);
          end loop;
        else
          for l in 0 to LANES - 1 loop
            if we(l) = '1' then
              for b in 0 to LANE - 1 loop
                mem(ad)(l * LANE + b) := di(l * LANE + b);
              end loop;
            end if;
          end loop;
          for i in DOA'range loop DOA(i) <= mem(ad)(i - DOA'low); end loop;
        end if;
      end if;
    end if;
  end process;

  port_b : process (CLKB)
    variable ad : natural range 0 to DEPTH - 1;
    variable di : std_logic_vector(WW - 1 downto 0);
    variable we : std_logic_vector(LANES - 1 downto 0);
  begin
    if rising_edge(CLKB) then
      ad := to_integer(unsigned(to_dn(ADDRB)));
      for i in DIB'range loop di(i - DIB'low) := DIB(i); end loop;
      for i in WEB'range loop we(i - WEB'low) := WEB(i); end loop;
      if ENB = '1' then
        if RSTB = '1' then
          for i in DOB'range loop
            DOB(i) <= to_stdlogicvector(SRVAL_B)(i - DOB'low);
          end loop;
        else
          for l in 0 to LANES - 1 loop
            if we(l) = '1' then
              for b in 0 to LANE - 1 loop
                mem(ad)(l * LANE + b) := di(l * LANE + b);
              end loop;
            end if;
          end loop;
          for i in DOB'range loop DOB(i) <= mem(ad)(i - DOB'low); end loop;
        end if;
      end if;
    end if;
  end process;

end architecture sim;
"""

# The behavioral arch cannot index INIT_xx generics in a loop (VHDL has no
# named-generic reflection), so we patch a INIT_VEC constant into the entity
# declaration of the derived copy: each INIT_xx is aliased into a 128-element
# bit_vector array constant referenced by the arch.


def bram_sim():
    outdir = Path(__file__).resolve().parent / "unimacro_sim"
    outdir.mkdir(parents=True, exist_ok=True)
    src = A2I / "sim" / "unimacro" / "bram_tdp_macro_mock.vhdl"
    txt = src.read_text()
    # inject `constant INIT_VEC : ...` referencing the INIT generics, and
    # replace the INIT_X(c) pseudo-usage in the arch with INIT_VEC(c).
    alias = "  constant INIT_VEC : t_init_vec := (INIT_00, INIT_01, INIT_02, INIT_03, INIT_04, INIT_05, INIT_06, INIT_07, INIT_08, INIT_09, INIT_0A, INIT_0B, INIT_0C, INIT_0D, INIT_0E, INIT_0F, INIT_10, INIT_11, INIT_12, INIT_13, INIT_14, INIT_15, INIT_16, INIT_17, INIT_18, INIT_19, INIT_1A, INIT_1B, INIT_1C, INIT_1D, INIT_1E, INIT_1F, INIT_20, INIT_21, INIT_22, INIT_23, INIT_24, INIT_25, INIT_26, INIT_27, INIT_28, INIT_29, INIT_2A, INIT_2B, INIT_2C, INIT_2D, INIT_2E, INIT_2F, INIT_30, INIT_31, INIT_32, INIT_33, INIT_34, INIT_35, INIT_36, INIT_37, INIT_38, INIT_39, INIT_3A, INIT_3B, INIT_3C, INIT_3D, INIT_3E, INIT_3F, INIT_40, INIT_41, INIT_42, INIT_43, INIT_44, INIT_45, INIT_46, INIT_47, INIT_48, INIT_49, INIT_4A, INIT_4B, INIT_4C, INIT_4D, INIT_4E, INIT_4F, INIT_50, INIT_51, INIT_52, INIT_53, INIT_54, INIT_55, INIT_56, INIT_57, INIT_58, INIT_59, INIT_5A, INIT_5B, INIT_5C, INIT_5D, INIT_5E, INIT_5F, INIT_60, INIT_61, INIT_62, INIT_63, INIT_64, INIT_65, INIT_66, INIT_67, INIT_68, INIT_69, INIT_6A, INIT_6B, INIT_6C, INIT_6D, INIT_6E, INIT_6F, INIT_70, INIT_71, INIT_72, INIT_73, INIT_74, INIT_75, INIT_76, INIT_77, INIT_78, INIT_79, INIT_7A, INIT_7B, INIT_7C, INIT_7D, INIT_7E, INIT_7F);\n"
    # insert generic-compatible constant into the entity (before 'end entity;')
    arch = BRAM_ARCH.replace("INIT_X(c)", "INIT_VEC(c)")
    (outdir / "bram_tdp_macro_sim.vhdl").write_text(txt + arch)
    print(f"bram: {outdir / 'bram_tdp_macro_sim.vhdl'}")


if __name__ == "__main__":
    for lib in ("ibm", "support", "clib", "tri"):
        shadow(lib)
    bram_sim()
