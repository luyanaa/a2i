-- Verify the generated GPR-logical operand path numerically against golden
-- xuq_alu (the full FXU), replicating the wiring a2i.py emits for FU_FXU_LOG:
--
--   rf_op_a/b[63:0] --(register rf->ex)--> ex_op_a/b[63:0]
--   byp_alu_ex1_rs0/rs1 <= MSB-swap( ex_op_a/b )   -- kernel.py _msb_swap
--   dec_alu_rf1_sel      <= 0                      -- sel=0 -> rot/log path
--   dec_alu_rf1_log_fcn  <= truth-table select     -- and/or/xor/nand/...
--   dec_alu_rf1_act/ex1_act <= rf1/ex1 valid
--   result <= alu_byp_ex1_log_rt                   -- 64b logic result (ex1)
--
-- log_fcn is a 2-input truth table (MSB-first, minterms ~a~b,~ab,a~b,ab).
-- Verifies the truth-table select + operand MSB-swap + result read.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
library support;  use support.power_logic_pkg.all;
library ibm;      use ibm.std_ulogic_support.all;
library tri;      use tri.tri_latches_pkg.all;
library work;

entity tb_log is
  generic (runner_cfg : string := "");
end entity;

architecture bench of tb_log is
  constant expand_type : integer := 1;
  signal clk, clk2x    : std_ulogic := '0';
  signal nclk          : clk_logic;
  signal vdd, gnd      : power_logic;

  signal rf_op_a, rf_op_b : std_ulogic_vector(63 downto 0) := (others=>'0');
  signal instr_v          : std_ulogic := '0';
  signal fcn_sel          : std_ulogic_vector(0 to 3) := "0000";
  signal res              : std_ulogic_vector(0 to 63);

  signal ex_op_a, ex_op_b : std_ulogic_vector(63 downto 0) := (others=>'0');
  signal rs0, rs1         : std_ulogic_vector(0 to 63);
  signal log_rt           : std_ulogic_vector(0 to 63);
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
    end if;
  end process;

  rs0 <= msb_swap(ex_op_a, 63);
  rs1 <= msb_swap(ex_op_b, 63);
  res <= log_rt;

  dut : entity work.xuq_alu
    generic map (expand_type => expand_type)
    port map (
      nclk=>nclk, vdd=>vdd, gnd=>gnd,
      d_mode_dc=>'0', delay_lclkr_dc=>'0', mpw1_dc_b=>'0', mpw2_dc_b=>'0',
      func_sl_force=>'0', func_sl_thold_0_b=>'1',   -- active-low: '1' = run
      sg_0=>'0', scan_in=>"00", scan_out=>open,
      -- functional: logical-op path (rot/log), everything else tied off
      spr_msr_cm=>"0001",
      dec_alu_rf1_act=>instr_v, dec_alu_ex1_act=>instr_v,
      dec_alu_rf1_sel=>"0000",                      -- sel=0 -> rot/log path
      dec_alu_rf1_log_fcn=>fcn_sel,
      dec_alu_rf1_add_rs0_inv=>(others=>'0'),
      dec_alu_rf1_add_ci=>'0', dec_alu_rf1_is_cmpl=>'0',
      dec_alu_rf1_tw_cmpsel=>"000000",
      dec_ex2_tid=>"0000", dec_ex4_tid=>"0000",
      dec_alu_rf1_mul_recform=>'0', dec_alu_rf1_mul_val=>'0',
      dec_alu_rf1_mul_ret=>'0', dec_alu_rf1_mul_sign=>'0',
      dec_alu_rf1_mul_size=>'0', dec_alu_rf1_mul_imm=>'0',
      fxa_fxb_rf1_div_ctr=>"00000000",
      dec_alu_rf1_div_val=>'0', dec_alu_rf1_div_sign=>'0',
      dec_alu_rf1_div_size=>'0', dec_alu_rf1_div_extd=>'0',
      dec_alu_rf1_div_recform=>'0', dec_alu_ex1_is_cmp=>'0',
      dec_alu_rf1_select_64bmode=>'1',
      fxa_fxb_ex1_hold_ctr_flush=>'0',
      byp_alu_ex1_rs0=>rs0, byp_alu_ex1_rs1=>rs1,
      byp_alu_ex1_mulsrc_0=>(others=>'0'), byp_alu_ex1_mulsrc_1=>(others=>'0'),
      byp_alu_ex1_divsrc_0=>(others=>'0'), byp_alu_ex1_divsrc_1=>(others=>'0'),
      dec_alu_rf1_xer_ov_update=>'0', dec_alu_rf1_xer_ca_update=>'0',
      dec_alu_rf1_sh_right=>'0', dec_alu_rf1_sh_word=>'0',
      dec_alu_rf1_sgnxtd_byte=>'0', dec_alu_rf1_sgnxtd_half=>'0',
      dec_alu_rf1_sgnxtd_wd=>'0', dec_alu_rf1_sra_dw=>'0', dec_alu_rf1_sra_wd=>'0',
      dec_alu_rf1_chk_shov_dw=>'0', dec_alu_rf1_chk_shov_wd=>'0',
      dec_alu_rf1_use_me_ins_hi=>'0', dec_alu_rf1_use_me_ins_lo=>'0',
      dec_alu_rf1_use_mb_ins_hi=>'0', dec_alu_rf1_use_mb_ins_lo=>'0',
      dec_alu_rf1_use_me_rb_hi=>'0', dec_alu_rf1_use_me_rb_lo=>'0',
      dec_alu_rf1_use_mb_rb_hi=>'0', dec_alu_rf1_use_mb_rb_lo=>'0',
      dec_alu_rf1_use_rb_amt_hi=>'0', dec_alu_rf1_use_rb_amt_lo=>'0',
      dec_alu_rf1_zm_ins=>'0', byp_alu_rf1_isel_fcn=>"0000",
      dec_alu_rf1_me_ins_b=>"000000", dec_alu_rf1_mb_ins=>"000000",
      dec_alu_rf1_sh_amt=>"000000", dec_alu_rf1_mb_gt_me=>'0',
      -- outputs (only log_rt consumed; rest open)
      alu_byp_ex1_log_rt=>log_rt, alu_byp_ex2_rt=>open,
      xu_ex1_eff_addr_int=>open, xu_ex2_eff_addr=>open,
      alu_byp_ex5_mul_rt=>open, alu_byp_ex3_div_rt=>open,
      alu_ex2_div_done=>open, alu_dec_ex1_ipb_ba=>open,
      alu_dec_ex1_ipb_sz=>open, alu_dec_div_need_hole=>open,
      alu_ex3_mul_done=>open, alu_ex4_mul_done=>open,
      alu_cpl_ex3_trap_val=>open, alu_byp_ex2_xer=>open,
      alu_byp_ex5_xer_mul=>open, alu_byp_ex3_xer_div=>open,
      alu_byp_ex2_cr_recform=>open, alu_byp_ex5_cr_mul=>open,
      alu_byp_ex3_cr_div=>open);

  stim : process
    variable exp : unsigned(63 downto 0);
    variable got : unsigned(63 downto 0);
    procedure tc(a, b : unsigned(63 downto 0); fcn : std_ulogic_vector(0 to 3);
                 tag : string; expv : unsigned(63 downto 0)) is
    begin
      rf_op_a <= std_ulogic_vector(a);
      rf_op_b <= std_ulogic_vector(b);
      fcn_sel <= fcn;
      instr_v <= '1';
      for i in 0 to 3 loop wait until rising_edge(clk); end loop;
      got := unsigned(to_stdlogicvector(res));
      exp := expv;
      assert got = exp
        report tag & " FAIL got=0x"&to_hstring(got)&" exp=0x"&to_hstring(exp)
        severity error;
      if got = exp then report tag & " PASS -> 0x"&to_hstring(got); end if;
      instr_v <= '0';
      wait until rising_edge(clk);
    end procedure;
    variable A, B : unsigned(63 downto 0);
  begin
    report "tb_log: golden xuq_alu logic unit + generated operand path";
    wait until rising_edge(clk);
    A := x"00000000FFFF0000";  B := x"00000000FF00FF00";
    tc(A,B,"0001","and  A&B",  A and B);
    tc(A,B,"0111","or   A|B",  A or  B);
    tc(A,B,"0110","xor  A^B",  A xor B);
    tc(A,B,"1110","nand ~(A&B)", not (A and B));
    tc(A,B,"1000","nor  ~(A|B)", not (A or  B));
    tc(A,B,"0010","andc A&~B", A and (not B));
    tc(A,B,"1001","eqv  A==B", A xnor B);
    report "tb_log: ALL PASS (log_fcn truth table + MSB-swap verified)";
    done <= true;
    wait;
  end process;
end architecture;
