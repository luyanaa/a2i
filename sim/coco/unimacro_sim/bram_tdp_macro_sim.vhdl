library ieee;
use ieee.std_logic_1164.all;

entity BRAM_TDP_MACRO is
  generic (
    BRAM_SIZE           : string;
    DEVICE              : string;
    DOA_REG             : integer;
    DOB_REG             : integer;
    INIT_A              : bit_vector;
    INIT_B              : bit_vector;
    INIT_FILE           : string;
    READ_WIDTH_A        : integer;
    READ_WIDTH_B        : integer;
    SIM_COLLISION_CHECK : string;
    SRVAL_A             : bit_vector;
    SRVAL_B             : bit_vector;
    WRITE_MODE_A        : string;
    WRITE_MODE_B        : string;
    WRITE_WIDTH_A       : integer;
    WRITE_WIDTH_B       : integer;
    INIT_00             : bit_vector;
    INIT_01             : bit_vector;
    INIT_02             : bit_vector;
    INIT_03             : bit_vector;
    INIT_04             : bit_vector;
    INIT_05             : bit_vector;
    INIT_06             : bit_vector;
    INIT_07             : bit_vector;
    INIT_08             : bit_vector;
    INIT_09             : bit_vector;
    INIT_0A             : bit_vector;
    INIT_0B             : bit_vector;
    INIT_0C             : bit_vector;
    INIT_0D             : bit_vector;
    INIT_0E             : bit_vector;
    INIT_0F             : bit_vector;
    INIT_10             : bit_vector;
    INIT_11             : bit_vector;
    INIT_12             : bit_vector;
    INIT_13             : bit_vector;
    INIT_14             : bit_vector;
    INIT_15             : bit_vector;
    INIT_16             : bit_vector;
    INIT_17             : bit_vector;
    INIT_18             : bit_vector;
    INIT_19             : bit_vector;
    INIT_1A             : bit_vector;
    INIT_1B             : bit_vector;
    INIT_1C             : bit_vector;
    INIT_1D             : bit_vector;
    INIT_1E             : bit_vector;
    INIT_1F             : bit_vector;
    INIT_20             : bit_vector;
    INIT_21             : bit_vector;
    INIT_22             : bit_vector;
    INIT_23             : bit_vector;
    INIT_24             : bit_vector;
    INIT_25             : bit_vector;
    INIT_26             : bit_vector;
    INIT_27             : bit_vector;
    INIT_28             : bit_vector;
    INIT_29             : bit_vector;
    INIT_2A             : bit_vector;
    INIT_2B             : bit_vector;
    INIT_2C             : bit_vector;
    INIT_2D             : bit_vector;
    INIT_2E             : bit_vector;
    INIT_2F             : bit_vector;
    INIT_30             : bit_vector;
    INIT_31             : bit_vector;
    INIT_32             : bit_vector;
    INIT_33             : bit_vector;
    INIT_34             : bit_vector;
    INIT_35             : bit_vector;
    INIT_36             : bit_vector;
    INIT_37             : bit_vector;
    INIT_38             : bit_vector;
    INIT_39             : bit_vector;
    INIT_3A             : bit_vector;
    INIT_3B             : bit_vector;
    INIT_3C             : bit_vector;
    INIT_3D             : bit_vector;
    INIT_3E             : bit_vector;
    INIT_3F             : bit_vector;
    INIT_40             : bit_vector;
    INIT_41             : bit_vector;
    INIT_42             : bit_vector;
    INIT_43             : bit_vector;
    INIT_44             : bit_vector;
    INIT_45             : bit_vector;
    INIT_46             : bit_vector;
    INIT_47             : bit_vector;
    INIT_48             : bit_vector;
    INIT_49             : bit_vector;
    INIT_4A             : bit_vector;
    INIT_4B             : bit_vector;
    INIT_4C             : bit_vector;
    INIT_4D             : bit_vector;
    INIT_4E             : bit_vector;
    INIT_4F             : bit_vector;
    INIT_50             : bit_vector;
    INIT_51             : bit_vector;
    INIT_52             : bit_vector;
    INIT_53             : bit_vector;
    INIT_54             : bit_vector;
    INIT_55             : bit_vector;
    INIT_56             : bit_vector;
    INIT_57             : bit_vector;
    INIT_58             : bit_vector;
    INIT_59             : bit_vector;
    INIT_5A             : bit_vector;
    INIT_5B             : bit_vector;
    INIT_5C             : bit_vector;
    INIT_5D             : bit_vector;
    INIT_5E             : bit_vector;
    INIT_5F             : bit_vector;
    INIT_60             : bit_vector;
    INIT_61             : bit_vector;
    INIT_62             : bit_vector;
    INIT_63             : bit_vector;
    INIT_64             : bit_vector;
    INIT_65             : bit_vector;
    INIT_66             : bit_vector;
    INIT_67             : bit_vector;
    INIT_68             : bit_vector;
    INIT_69             : bit_vector;
    INIT_6A             : bit_vector;
    INIT_6B             : bit_vector;
    INIT_6C             : bit_vector;
    INIT_6D             : bit_vector;
    INIT_6E             : bit_vector;
    INIT_6F             : bit_vector;
    INIT_70             : bit_vector;
    INIT_71             : bit_vector;
    INIT_72             : bit_vector;
    INIT_73             : bit_vector;
    INIT_74             : bit_vector;
    INIT_75             : bit_vector;
    INIT_76             : bit_vector;
    INIT_77             : bit_vector;
    INIT_78             : bit_vector;
    INIT_79             : bit_vector;
    INIT_7A             : bit_vector;
    INIT_7B             : bit_vector;
    INIT_7C             : bit_vector;
    INIT_7D             : bit_vector;
    INIT_7E             : bit_vector;
    INIT_7F             : bit_vector;
    INITP_00            : bit_vector;
    INITP_01            : bit_vector;
    INITP_02            : bit_vector;
    INITP_03            : bit_vector;
    INITP_04            : bit_vector;
    INITP_05            : bit_vector;
    INITP_06            : bit_vector;
    INITP_07            : bit_vector;
    INITP_08            : bit_vector;
    INITP_09            : bit_vector;
    INITP_0A            : bit_vector;
    INITP_0B            : bit_vector;
    INITP_0C            : bit_vector;
    INITP_0D            : bit_vector;
    INITP_0E            : bit_vector;
    INITP_0F            : bit_vector
    );
port (
  DOA    : out std_logic_vector;
  DOB    : out std_logic_vector;
  ADDRA  : in  std_logic_vector;
  ADDRB  : in  std_logic_vector;
  CLKA   : in  std_ulogic;
  CLKB   : in  std_ulogic;
  DIA    : in  std_logic_vector;
  DIB    : in  std_logic_vector;
  ENA    : in  std_ulogic;
  ENB    : in  std_ulogic;
  REGCEA : in  std_ulogic;
  REGCEB : in  std_ulogic;
  RSTA   : in  std_ulogic;
  RSTB   : in  std_ulogic;
  WEA    : in  std_logic_vector;
  WEB    : in  std_logic_vector
  );
end entity;


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
