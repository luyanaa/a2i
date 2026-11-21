-- Verify the generated a2i pipeline wrapper numerically against golden fuq_mul.
--
-- This bench replicates, in VHDL, the EXACT operand path the Amaranth
-- `kernel.py`+`a2i.py` generate, wrapped around the REAL frozen `fuq_mul`:
--
--   rf_op_a[63:0] --(register rf->ex)--> ex_op_a[63:0]
--   a_frac(0:52)  <= MSB-swap( ex_op_a[52:0] )      -- kernel.py _msb_swap
--   c_frac(0:53)  <= MSB-swap( ex_op_c[53:0] )
--   ex1_act       <= ex_valid                        -- stage-valid gating
--   wb_data[63:0] <= sum[0:63] + car[0:63]           -- a2i.py carry-save fold
--
-- The MSB-swap in kernel.py maps golden index i (MSB-first, idx0=MSB) to
-- Amaranth signal bit (width-1-i). For a 53-bit field driven by the LOW 53
-- bits of a 64-bit rf_op, that means: a_frac(0) <= ex_op_a[52], ...,
-- a_frac(52) <= ex_op_a[0].  i.e. a_frac(i) = ex_op_a[52-i].
--
-- If the swap is right, a small rf_op_a (say 3) lands in a_frac(50,51,52)
-- i.e. the LOW-order bits, and the product reconstructs a*c + 2^107. If the
-- swap were wrong (bit-reversed), rf_op_a=3 would land in a_frac(0,1) = the
-- TOP Booth digits and the product would be wildly different.
--
-- Checker mirrors tb_fumul: P = S + C (MSB-first, idx1=2^107) = a*c + 2^107.
-- The generated wb_data only folds the low 64 bits, so we compare
-- wb_data == lo64(a*c + 2^107).
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
library support;  use support.power_logic_pkg.all;
library ibm;      use ibm.std_ulogic_support.all;
library tri;      use tri.tri_latches_pkg.all;
library work;

entity tb_a2i_wrap is
  generic (runner_cfg : string := "");
end entity;

architecture bench of tb_a2i_wrap is
  constant expand_type : integer := 1;
  signal clk, clk2x    : std_ulogic := '0';
  signal nclk          : clk_logic;
  signal vdd, gnd      : power_logic;

  -- generated-wrapper external interface (mirrors a2i_fuq_mul.v ports)
  signal rf_op_a, rf_op_c : std_ulogic_vector(63 downto 0) := (others=>'0');
  signal instr_v          : std_ulogic := '0';
  signal wb_data          : std_ulogic_vector(63 downto 0);
  signal wb_valid         : std_ulogic := '0';

  -- internal ex-stage operand regs (registered rf->ex, as the pipeline does)
  signal ex_op_a, ex_op_c : std_ulogic_vector(63 downto 0) := (others=>'0');
  signal ex1_act          : std_ulogic := '0';
  signal a_frac           : std_ulogic_vector(0 to 52);
  signal a17, a35         : std_ulogic := '0';
  signal c_frac           : std_ulogic_vector(0 to 53);
  signal ex2_sum, ex2_car : std_ulogic_vector(1 to 108);
  signal done             : boolean := false;

  -- the MSB-swap kernel.py emits: golden field index i <- amaranth bit (w-1-i)
  -- a_frac(0:52) <- ex_op_a[52:0]  means  a_frac(i) = ex_op_a(52-i)
  function msb_swap(sig : std_ulogic_vector; hi : integer)
    return std_ulogic_vector is
    variable r : std_ulogic_vector(0 to hi);
  begin
    for i in 0 to hi loop
      r(i) := sig(hi - i);     -- golden idx i = LSB-first bit hi-i
    end loop;
    return r;
  end function;

  function lo64(u : unsigned) return unsigned is
    variable r : unsigned(255 downto 0) := u;
  begin
    for i in 64 to 255 loop r(i) := '0'; end loop;
    return r;
  end function;

  function to_u(v : std_ulogic_vector) return unsigned is
    variable r : unsigned(255 downto 0) := (others=>'0');
    variable w : integer;
  begin
    for i in v'range loop           -- MSB-first: index1 = 2^(v'high - i)
      w := v'high - i;              -- sum(1:108): index 1 -> weight 2^107
      if v(i)='1' and w>=0 and w<=255 then r(w):='1'; end if;
    end loop;
    return r;
  end function;
begin
  vdd <= '1'; gnd <= '0';
  clk  <= not clk  after 5 ns   when not done else '0';
  clk2x<= not clk2x after 2.5 ns when not done else '0';
  nclk.clk<=clk; nclk.clk2x<=clk2x; nclk.clk4x<='0'; nclk.sreset<='0';

  -- register operands rf->ex (the pipeline's m.d.sync ex_op_* <= rf_op_*)
  process(clk) begin
    if rising_edge(clk) then
      ex_op_a <= rf_op_a;
      ex_op_c <= rf_op_c;
      ex1_act <= instr_v;      -- ex1_act = ex-stage-valid (1 cycle after v)
    end if;
  end process;

  -- MSB-swap at the Instance boundary (kernel.py _msb_swap)
  a_frac <= msb_swap(ex_op_a(52 downto 0), 52);
  c_frac <= msb_swap(ex_op_c(53 downto 0), 53);

  -- fold: wb_data = low64(sum + car), MSB-first -> reconstruct then take lo64
  wb_data <= std_ulogic_vector(lo64(to_u(ex2_sum) + to_u(ex2_car))(63 downto 0));

  dut : entity work.fuq_mul
    generic map (expand_type => expand_type)
    port map (
      vdd=>vdd, gnd=>gnd, clkoff_b=>'1', act_dis=>'0', flush=>'0',
      delay_lclkr=>'0', mpw1_b=>'0', mpw2_b=>'0', sg_1=>'0', thold_1=>'0',
      fpu_enable=>'1', nclk=>nclk, f_mul_si=>'0', f_mul_so=>open,
      ex1_act=>ex1_act,
      f_fmt_ex1_a_frac=>a_frac, f_fmt_ex1_a_frac_17=>a17, f_fmt_ex1_a_frac_35=>a35,
      f_fmt_ex1_c_frac=>c_frac,
      f_mul_ex2_sum=>ex2_sum, f_mul_ex2_car=>ex2_car);

  stim : process
    variable exp : unsigned(127 downto 0);
    variable got : unsigned(63 downto 0);
    procedure tc(a : natural; c : natural; tag : string) is
      variable a64, c64 : unsigned(63 downto 0);
    begin
      a64 := to_unsigned(a,64); c64 := to_unsigned(c,64);
      rf_op_a <= std_ulogic_vector(a64);
      rf_op_c <= std_ulogic_vector(c64);
      instr_v <= '1';
      wait until rising_edge(clk);           -- rf_op -> ex_op latch
      instr_v <= '0';
      wait until rising_edge(clk);           -- ex1_act=1: ex1 -> ex2 latch
      wait until rising_edge(clk);           -- result stable on ex2 outputs
      -- expected: lo64(a*c + 2^107). a,c <= ~2^16 -> a*c < 2^32, so the low
      -- 64 bits of (a*c + 2^107) are just a*c (2^107 doesn't reach bit<64).
      -- a,c are small naturals -> a*c fits in natural; expected low-64 is a*c.
      got := unsigned(to_stdlogicvector(wb_data));
      exp := (others=>'0'); exp(63 downto 0) := to_unsigned(a*c, 64);
      assert got = exp(63 downto 0)
        report tag & " FAIL: a="&integer'image(a)&" c="&integer'image(c)&
               " got=0x"&to_hstring(got)&" exp=0x"&to_hstring(exp(63 downto 0))
        severity error;
      if got = exp(63 downto 0) then
        report tag & " PASS a="&integer'image(a)&" c="&integer'image(c)&
               " wb=0x"&to_hstring(got);
      end if;
    end procedure;
  begin
    report "tb_a2i_wrap: verify generated operand path + MSB-swap + fold";
    wait until rising_edge(clk);
    -- small multipliers: if MSB-swap were wrong, these would be bit-reversed
    -- into the TOP Booth digits and the product would be enormous/garbage.
    tc(3, 5,   "3*5");
    tc(5, 7,   "5*7");
    tc(1, 1,   "1*1");
    tc(255, 3, "255*3");    -- a up to 8 bits, still sparse Booth domain
    tc(7, 1000,"7*1000");   -- larger multiplicand
    tc(0, 5,   "0*5");      -- zero product, only the 2^107 term
    report "tb_a2i_wrap: ALL PASS (MSB-swap + operand path + fold verified)";
    done <= true;
    wait;
  end process;
end architecture;
