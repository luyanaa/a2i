-- VUnit unit bench for the frozen A2I address-generation leaf `xuq_agen`.
--
-- DUT contract (xuq_agen.vhdl): purely combinational adder cluster, NO clock.
--   x(0 to 63) + y(0 to 63), MSB-first (index 0 = weight 2^63, index 63 = 2^0).
--   The 64-bit add is split: `kog` (xuq_agen_lo) is an independent 12-bit
--   adder over the LOW 12 bits x(52:63)+y(52:63) (chain starts at index 63,
--   carry-in 0); the byte carry-select adder covers the HIGH 52 bits (bytes
--   0..5 over indices 0..47 plus csmuxe over 48..51) with carry-in c64_b(7)
--   = carry-out of the low-12 adder. Hence:
--   - sum_non_erat(0 to 51) = high 52 bits of (x+y); sum_non_erat(52 to 63) =
--     low 12 bits of (x+y) → sum_non_erat = (x + y) mod 2^64 (no constant
--     term, verified empirically).
--   - sum(0 to 51) = buffered copy of the high field → (x+y) >> 12.
--   - sum_arr_dir01/23/45/67(53 to 57): quad-buffered copy of the kog sum bits
--     53..57 → equal to bits 53..57 of (x+y) mod 2^64.
--   - ary_write_act*/match_oth come from the directory compare (xuq_agen_cmp);
--     with the sane-default controls they must simply be driven (0/1, not 'X').
--   Snoop path: with snoop_sel='1', binv_val='0' the byte muxes select
--   snoop_addr instead of the adder for bits 0..51, so sum(0:51) = snoop_addr
--   (MSB-first over 0..51, verified empirically below).
--
-- Control defaults: snoop_sel='0', binv_val='0', mode64='1', dir_ig_57_b='1',
-- inv1_val_b='1', ex1_cache_acc_b='0', rel3_val='0', z=way=snoop_addr=0.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.math_real.all;
library vunit_lib;
context vunit_lib.vunit_context;
library support;  use support.power_logic_pkg.all;
library ibm;      use ibm.std_ulogic_support.all;
library tri;      use tri.tri_latches_pkg.all;
library top;

entity tb_xuagen is
  generic (runner_cfg : string := "");
end entity;

architecture bench of tb_xuagen is
  constant expand_type : integer := 1;   -- pure-RTL path (unused by DUT outputs here)
  constant settle : delay_length := 2 ns;

  signal vdd, gnd    : power_logic;
  signal x           : std_ulogic_vector(0 to 63) := (others => '0');
  signal y           : std_ulogic_vector(0 to 63) := (others => '0');
  signal snoop_addr  : std_ulogic_vector(0 to 51) := (others => '0');
  signal snoop_sel   : std_ulogic := '0';
  signal binv_val    : std_ulogic := '0';
  signal mode64      : std_ulogic := '1';
  signal dir_ig_57_b : std_ulogic := '1';
  signal z           : std_ulogic_vector(53 to 57) := (others => '0');
  signal way         : std_ulogic_vector(0 to 7)   := (others => '0');
  signal inv1_val_b  : std_ulogic := '1';
  signal ex1_cache_acc_b : std_ulogic := '0';
  signal rel3_val    : std_ulogic := '0';

  signal sum_non_erat   : std_ulogic_vector(0 to 63);
  signal sum            : std_ulogic_vector(0 to 51);
  signal sum_arr_dir01  : std_ulogic_vector(53 to 57);
  signal sum_arr_dir23  : std_ulogic_vector(53 to 57);
  signal sum_arr_dir45  : std_ulogic_vector(53 to 57);
  signal sum_arr_dir67  : std_ulogic_vector(53 to 57);
  signal ary_write_act_01 : std_ulogic;
  signal ary_write_act_23 : std_ulogic;
  signal ary_write_act_45 : std_ulogic;
  signal ary_write_act_67 : std_ulogic;
  signal ary_write_act    : std_ulogic_vector(0 to 3);
  signal match_oth        : std_ulogic;

  signal done : boolean := false;

  -- Numeric value of an MSB-first/LSB-first vector (see tb_fumul).
  function to_unsigned_nat(v : std_ulogic_vector; msb_first : boolean)
    return unsigned is
    variable r : unsigned(255 downto 0) := (others => '0');
    variable w : integer;
  begin
    for i in v'range loop
      if v(i) = '1' then
        if msb_first then w := v'high - i; else w := i - v'low; end if;
        if w >= 0 and w <= 255 then r(w) := '1'; end if;
      end if;
    end loop;
    return r;
  end function;

  -- Build a std_ulogic_vector in the DUT's index direction from a value.
  function to_suv(u : unsigned; lo, hi : integer; msb_first : boolean)
    return std_ulogic_vector is
    variable r : std_ulogic_vector(lo to hi);
  begin
    for i in lo to hi loop
      if msb_first then
        r(i) := u(hi - i);                       -- index lo = MSB
      else
        r(i) := u(i - lo);                       -- index lo = LSB
      end if;
    end loop;
    return r;
  end function;

  -- Keep the low n bits of a wide unsigned.
  function lo_n(u : unsigned; n : integer) return unsigned is
    variable r : unsigned(255 downto 0) := u;
  begin
    for i in n to 255 loop r(i) := '0'; end loop;
    return r;
  end function;

  -- 64-bit add reduced mod 2^64 (operands given LSB-first as 64-bit unsigned).
  function mod64(a : unsigned(63 downto 0); b : unsigned(63 downto 0))
    return unsigned is
    variable r : unsigned(255 downto 0);
  begin
    r := resize(a, 256) + resize(b, 256);
    return lo_n(r, 64);
  end function;

  -- True when a std_ulogic is at a valid binary level (driven-check helper).
  function is_bin(s : std_ulogic) return boolean is
  begin
    return (s = '0') or (s = '1');
  end function;

  -- True when a short vector holds only valid binary levels.
  function is_bin_vec(v : std_ulogic_vector) return boolean is
  begin
    for i in v'range loop
      if not is_bin(v(i)) then return false; end if;
    end loop;
    return true;
  end function;
begin
  vdd <= '1';  gnd <= '0';

  dut : entity top.xuq_agen
    generic map (expand_type => expand_type)
    port map (
      x=>x, y=>y, snoop_addr=>snoop_addr, snoop_sel=>snoop_sel,
      binv_val=>binv_val, mode64=>mode64, dir_ig_57_b=>dir_ig_57_b,
      sum_non_erat=>sum_non_erat, sum=>sum,
      sum_arr_dir01=>sum_arr_dir01, sum_arr_dir23=>sum_arr_dir23,
      sum_arr_dir45=>sum_arr_dir45, sum_arr_dir67=>sum_arr_dir67,
      z=>z, way=>way, inv1_val_b=>inv1_val_b,
      ex1_cache_acc_b=>ex1_cache_acc_b, rel3_val=>rel3_val,
      ary_write_act_01=>ary_write_act_01, ary_write_act_23=>ary_write_act_23,
      ary_write_act_45=>ary_write_act_45, ary_write_act_67=>ary_write_act_67,
      ary_write_act=>ary_write_act, match_oth=>match_oth,
      vdd=>vdd, gnd=>gnd);

  stim : process
    variable seed1, seed2 : positive := 1;
    variable rv : real;

    procedure drive(xv, yv : unsigned(63 downto 0)) is
    begin
      x <= to_suv(xv, 0, 63, true);
      y <= to_suv(yv, 0, 63, true);
      wait for settle;
    end procedure;

    procedure drive_snoop(sa : unsigned(51 downto 0)) is
    begin
      x <= to_suv(to_unsigned(0, 64), 0, 63, true);
      y <= to_suv(to_unsigned(0, 64), 0, 63, true);
      snoop_addr <= to_suv(sa, 0, 51, true);
      snoop_sel  <= '1';
      binv_val   <= '0';
      wait for settle;
    end procedure;

    -- Primary golden check: full 64-bit sum_non_erat = (x+y) mod 2^64.
    procedure check_case(xv, yv : unsigned(63 downto 0); tag : string) is
      variable got, exp : unsigned(255 downto 0);
    begin
      drive(xv, yv);
      got := to_unsigned_nat(sum_non_erat, true);
      exp := mod64(xv, yv);
      check_equal(got, exp, "sum_non_erat " & tag);
      -- Secondary: ERAT field sum(0:51) covers the HIGH 52 bits
      -- (weights 2^63..2^12), with carry-in from the low-12 kog adder:
      -- sum = (x+y) >> 12.
      check_equal(shift_right(exp, 12), lo_n(shift_right(exp, 12), 52), "sum " & tag);
      -- Secondary: array-dir quad buffers = word bits 53..57 (weights
      -- 2^10..2^6), i.e. exp(63-k).
      for k in 53 to 57 loop
        check_equal(sum_arr_dir01(k), exp(63-k), "dir01 b" & integer'image(k) & " " & tag);
        check_equal(sum_arr_dir23(k), exp(63-k), "dir23 b" & integer'image(k) & " " & tag);
        check_equal(sum_arr_dir45(k), exp(63-k), "dir45 b" & integer'image(k) & " " & tag);
        check_equal(sum_arr_dir67(k), exp(63-k), "dir67 b" & integer'image(k) & " " & tag);
      end loop;
      -- Side outputs must be driven (valid '0'/'1', never meta values).
      check_equal(is_bin(ary_write_act_01), true, "act01 driven " & tag);
      check_equal(is_bin(ary_write_act_23), true, "act23 driven " & tag);
      check_equal(is_bin(ary_write_act_45), true, "act45 driven " & tag);
      check_equal(is_bin(ary_write_act_67), true, "act67 driven " & tag);
      check_equal(is_bin_vec(ary_write_act), true, "act vec driven " & tag);
      check_equal(is_bin(match_oth), true, "match_oth driven " & tag);
    end procedure;

    -- Snoop-path check: with snoop_sel=1, binv_val=0 the byte muxes output
    -- snoop_addr on sum(0:51), MSB-first over 0..51 → value = sa directly.
    procedure check_snoop(sa : unsigned(51 downto 0); tag : string) is
      variable got : unsigned(255 downto 0);
    begin
      drive_snoop(sa);
      got := to_unsigned_nat(sum, true);
      check_equal(got, lo_n(resize(sa, 256), 64), "snoop " & tag);
      snoop_sel <= '0';
    end procedure;
    variable xv, yv : unsigned(63 downto 0);
  begin
    test_runner_setup(runner, runner_cfg);
    if run("xuq_agen") then
      -- Deterministic corners.
      check_case(to_unsigned(0, 64), to_unsigned(0, 64), "zero");
      check_case(to_unsigned(3, 64), to_unsigned(5, 64), "small 3+5");
      check_case(to_unsigned(1, 64), to_unsigned(1, 64), "1+1");
      -- Single-hot bit at several positions (MSB, mid, LSB field boundaries).
      for b in 0 to 63 loop
        if b = 0 or b = 12 or b = 31 or b = 40 or b = 51 or b = 52 or b = 57 or b = 63 then
          check_case(shift_left(to_unsigned(1, 64), b), to_unsigned(0, 64),
                     "hot x b" & integer'image(b));
          check_case(to_unsigned(0, 64), shift_left(to_unsigned(1, 64), b),
                     "hot y b" & integer'image(b));
        end if;
      end loop;
      -- Crossing the 52-bit ERAT field boundary: (2^52-1) + 1.
      check_case(unsigned'(x"000FFFFFFFFFFFFF"), to_unsigned(1, 64), "b52 carry");
      -- All-ones boundaries.
      check_case(x"FFFFFFFFFFFFFFFF", x"FFFFFFFFFFFFFFFF", "ones+ones");
      check_case(x"FFFFFFFFFFFFFFFF", to_unsigned(1, 64), "ones+1");
      check_case(x"FFFFFFFFFFFFFFFF", shift_left(to_unsigned(1, 64), 63), "ones+msb");
      check_case(shift_left(to_unsigned(1, 64), 63), shift_left(to_unsigned(1, 64), 63),
                 "msb+msb");
      check_case(shift_left(to_unsigned(1, 64), 52), shift_left(to_unsigned(1, 64), 52),
                 "b52+b52");
      check_case(shift_left(to_unsigned(1, 64), 51), shift_left(to_unsigned(1, 64), 51),
                 "b51+b51");

      -- Randomized sweep, fully dense 64-bit operands.
      for i in 1 to 50 loop
        xv := (others => '0');
        yv := (others => '0');
        for b in 0 to 63 loop
          uniform(seed1, seed2, rv);
          if rv > 0.5 then xv(b) := '1'; end if;
          uniform(seed1, seed2, rv);
          if rv > 0.5 then yv(b) := '1'; end if;
        end loop;
        check_case(xv, yv, "rand " & integer'image(i));
      end loop;

      -- Snoop mux path (bits 0:51 select snoop_addr).
      check_snoop(to_unsigned(0, 52), "snoop zero");
      check_snoop(shift_left(to_unsigned(1, 52), 0), "snoop lsb");
      check_snoop(shift_left(to_unsigned(1, 52), 51), "snoop msb");

      report "xuq_agen: domain + 50 random vectors passed";
    end if;
    done <= true;
    test_runner_cleanup(runner);
    wait;
  end process;
end architecture;
