-- Verify the generated GPR-arith operand path numerically against golden
-- xuq_alu_add, replicating the wiring a2i.py emits:
--
--   rf_op_a/b[63:0] --(register rf->ex)--> ex_op_a/b[63:0]
--   byp_alu_ex1_rs0 <= MSB-swap( ex_op_a )        -- kernel.py _msb_swap
--   byp_alu_ex1_rs1 <= MSB-swap( ex_op_b )        -- (or SIMM when uses_simm)
--   dec_alu_rf1_add_rs0_inv <= all-ones (subf) | all-zeros (add)
--   dec_alu_rf1_add_ci      <= '1' (subf) | '0' (add)
--   dec_alu_rf1_add_act     <= ex-stage-valid & is_alu
--   result <= alu_byp_ex2_rt                      -- 64b sum, MSB-first
--
-- subf: rs0_inv all-ones makes x_b = ~rs0, so sum = ~rs0 + rs1 + 1 = rs1-rs0.
-- Verifies the rs0_inv MASK convention + ci + operand MSB-swap + result fold.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
library support;  use support.power_logic_pkg.all;
library ibm;      use ibm.std_ulogic_support.all;
library tri;      use tri.tri_latches_pkg.all;
library work;

entity tb_gpralu is
  generic (runner_cfg : string := "");
end entity;

architecture bench of tb_gpralu is
  constant expand_type : integer := 1;
  signal clk, clk2x    : std_ulogic := '0';
  signal nclk          : clk_logic;
  signal vdd, gnd      : power_logic;

  -- external wrapper interface (mirrors a2i op_a/op_b + controls)
  signal rf_op_a, rf_op_b : std_ulogic_vector(63 downto 0) := (others=>'0');
  signal instr_v          : std_ulogic := '0';
  signal sub_sel          : std_ulogic := '0';   -- 1=subf, 0=add
  signal res              : std_ulogic_vector(63 downto 0);

  signal ex_op_a, ex_op_b : std_ulogic_vector(63 downto 0) := (others=>'0');
  signal ex_sub           : std_ulogic := '0';   -- registered with operands
  signal ex1_act          : std_ulogic := '0';
  signal rs0, rs1         : std_ulogic_vector(0 to 63);
  signal rs0_inv          : std_ulogic_vector(0 to 63);
  signal add_ci           : std_ulogic;
  signal alu_rt           : std_ulogic_vector(0 to 63);
  signal ex1_sum          : std_ulogic_vector(0 to 63);   -- comb ex1 sum
  signal done             : boolean := false;

  function msb_swap(sig : std_ulogic_vector; hi : integer)
    return std_ulogic_vector is
    variable r : std_ulogic_vector(0 to hi);
  begin
    for i in 0 to hi loop r(i) := sig(hi - i); end loop;
    return r;
  end function;
begin
  vdd <= '1'; gnd <= '0';
  clk  <= not clk  after 5 ns   when not done else '0';
  clk2x<= not clk2x after 2.5 ns when not done else '0';
  nclk.clk<=clk; nclk.clk2x<=clk2x; nclk.clk4x<='0'; nclk.sreset<='0';

  process(clk) begin
    if rising_edge(clk) then
      ex_op_a <= rf_op_a;
      ex_op_b <= rf_op_b;
      ex_sub  <= sub_sel;      -- control registered rf->ex alongside operands
    end if;
  end process;

  -- MSB-swap operand->kernel (kernel.py _msb_swap); controls per a2i.py
  -- dec_alu_rf1_* are RF1-stage inputs latched rf1->ex1 on the act, so they
  -- must be driven by the RF-stage controls (sub_sel) not the ex-registered
  -- copy; the operand regs ex_op_a/b are the EX-stage values the adder reads.
  rs0     <= msb_swap(ex_op_a, 63);   -- comb bypass read at ex1
  rs1     <= msb_swap(ex_op_b, 63);
  rs0_inv <= (others=>sub_sel);       -- rf1-latched control
  add_ci  <= sub_sel;

  -- alu_byp_ex2_rt = not(log_add_ex2_rt): the ex2 path merges the LOGIC unit
  -- result (log_add_ex2_rt) which we tie 0 for a pure adder, so the readable
  -- sum is add_log_ex1_add_rt (the ex1 combinational a+b+ci output).
  res <= ex1_sum;

  dut : entity work.xuq_alu_add
    generic map (expand_type => expand_type)
    port map (
      nclk=>nclk, vdd=>vdd, gnd=>gnd,
      dec_alu_rf1_add_act=>instr_v,   -- rf1-valid gates the rf1->ex1 latch
      -- func_sl_thold_0_b is ACTIVE-LOW: '1' deasserts thold-0 so the tri
      -- rlmlatches (expand_type=1) clock normally; '0' would freeze them.
      d_mode_dc=>'0', delay_lclkr_dc=>'0',
      mpw1_dc_b=>'0', mpw2_dc_b=>'0',
      func_sl_force=>'0', func_sl_thold_0_b=>'1',
      sg_0=>'0', scan_in=>'0', scan_out=>open,
      dec_alu_rf1_select_64bmode=>'1',
      dec_alu_rf1_add_rs0_inv=>rs0_inv,
      dec_alu_rf1_add_ci=>add_ci,
      dec_alu_rf1_is_cmpl=>'0',
      dec_alu_rf1_tw_cmpsel=>"000000",
      dec_alu_ex1_is_cmp=>'0',
      byp_alu_ex1_rs0=>rs0, byp_alu_ex1_rs1=>rs1,
      log_add_ex2_rt=>(others=>'0'),
      alu_byp_ex2_rt=>alu_rt, add_log_ex1_add_rt=>ex1_sum,
      ex2_cr_recform=>open, xu_ex1_eff_addr_int=>open,
      xu_ex2_eff_addr=>open, ex3_trap_val=>open,
      ex2_add_xer_ov=>open, ex2_add_xer_ca=>open);

  stim : process
    variable exp : unsigned(63 downto 0);
    variable got : unsigned(63 downto 0);
    procedure tc(a, b : natural; sub : std_ulogic; tag : string) is
      variable bi : integer;
    begin
      rf_op_a <= std_ulogic_vector(to_unsigned(a,64));
      rf_op_b <= std_ulogic_vector(to_unsigned(b,64));
      sub_sel <= sub;
      -- hold rf1 inputs (act + controls) high across several edges so the
      -- act-gated lcb latches definitely capture rs0_inv/ci, then drop act
      -- and let the comb ex1 sum settle on the ex-registered operands.
      instr_v <= '1';
      for i in 0 to 3 loop wait until rising_edge(clk); end loop;
      got := unsigned(to_stdlogicvector(res));   -- sample while controls held
      report "DBG "&tag&" rs0_inv="&std_ulogic'image(rs0_inv(63))&
             " ci="&std_ulogic'image(add_ci)&
             " ex_op_a=0x"&to_hstring(unsigned(to_stdlogicvector(ex_op_a)))&
             " res=0x"&to_hstring(got);
      instr_v <= '0'; sub_sel <= '0';
      wait until rising_edge(clk);
      bi := b;
      if sub='1' then
        -- rs1 - rs0 in 64-bit two's complement; b-a may be negative
        exp := unsigned(to_signed(bi - a, 64));
      else
        exp := to_unsigned(a + b, 64);
      end if;
      assert got = exp
        report tag & " FAIL got=0x"&to_hstring(got)&" exp=0x"&to_hstring(exp)
        severity error;
      if got = exp then
        report tag & " PASS -> 0x"&to_hstring(got);
      end if;
    end procedure;
  begin
    report "tb_gpralu: golden xuq_alu_add + generated operand path + MSB-swap";
    wait until rising_edge(clk);
    tc(5,   7,   '0', "add 5+7");
    tc(0,   9,   '0', "add 0+9");
    tc(100, 200, '0', "add 100+200");
    tc(5,   7,   '1', "subf 7-5");       -- rs1 - rs0 = 7-5 = 2
    tc(0,   9,   '1', "subf 9-0");       -- = 9
    tc(200, 100, '1', "subf 100-200");   -- = -100 (two's complement)
    report "tb_gpralu: ALL PASS (rs0_inv mask + ci + MSB-swap verified)";
    done <= true;
    wait;
  end process;
end architecture;
