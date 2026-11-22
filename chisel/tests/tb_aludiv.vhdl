-- Probe + verify the GPR divide path on golden xuq_alu (xuq_alu_div inside),
-- replicating the wiring a2i.py emits for a div op:
--
--   rf_op_a/b[63:0] --(register rf->ex)--> ex_op_a/b[63:0]
--   byp_alu_ex1_divsrc_0 <= MSB-swap( ex_op_a )   -- NUM / dividend / RA
--   byp_alu_ex1_divsrc_1 <= MSB-swap( ex_op_b )   -- DEN / divisor  / RB
--   dec_alu_rf1_div_{val,sign,size,extd,recform} <= rf1-latched controls
--   fxa_fxb_rf1_div_ctr  <= iteration count (radix-16 engine recirculations)
--   result <= alu_byp_ex3_div_rt                   -- quotient (ex3)
--
-- xuq_alu_div is a multi-cycle iterative divider: div_val launches it, the
-- engine recirculates ex1->ex2 div_ctr times, alu_ex2_div_done pulses, and
-- the quotient is readable on alu_byp_ex3_div_rt.
-- Controls (xuq_dec_b): size 0=32b(divw) 1=64b(divd); extd=extended(divwe/de);
-- sign 1=signed; val launches.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
library support;  use support.power_logic_pkg.all;
library ibm;      use ibm.std_ulogic_support.all;
library tri;      use tri.tri_latches_pkg.all;
library work;

entity tb_aludiv is
  generic (runner_cfg : string := "");
end entity;

architecture bench of tb_aludiv is
  constant expand_type : integer := 1;
  signal clk, clk2x    : std_ulogic := '0';
  signal nclk          : clk_logic;
  signal vdd, gnd      : power_logic;

  signal rf_op_a, rf_op_b : std_ulogic_vector(63 downto 0) := (others=>'0');
  signal instr_v          : std_ulogic := '0';
  signal div_sign         : std_ulogic := '1';
  signal div_size         : std_ulogic := '0';
  signal div_extd         : std_ulogic := '0';
  signal div_ctr          : std_ulogic_vector(0 to 7) := "00000100";
  signal res              : std_ulogic_vector(0 to 63);
  signal ddone            : std_ulogic;
  signal hole             : std_ulogic;
  signal xer_ov           : std_ulogic_vector(0 to 3);

  signal ex_op_a, ex_op_b : std_ulogic_vector(63 downto 0) := (others=>'0');
  signal d0, d1           : std_ulogic_vector(0 to 63);
  signal div_rt           : std_ulogic_vector(0 to 63);
  signal done             : boolean := false;
  signal cyc              : integer := 0;


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
      cyc <= cyc + 1;
      if ddone='1' then
        report "DONE CYC" & integer'image(cyc) &
               " div_rt=0x" & to_hstring(unsigned(to_stdlogicvector(div_rt)));
      end if;
    end if;
  end process;

  d0 <= msb_swap(ex_op_a, 63);
  d1 <= msb_swap(ex_op_b, 63);
  res <= div_rt;

  dut : entity work.xuq_alu
    generic map (expand_type => expand_type)
    port map (
      nclk=>nclk, vdd=>vdd, gnd=>gnd,
      d_mode_dc=>'0', delay_lclkr_dc=>'0', mpw1_dc_b=>'0', mpw2_dc_b=>'0',
      func_sl_force=>'0', func_sl_thold_0_b=>'1',
      sg_0=>'0', scan_in=>"00", scan_out=>open,
      spr_msr_cm=>"0001",
      dec_alu_rf1_act=>instr_v, dec_alu_ex1_act=>instr_v,
      dec_alu_rf1_sel=>"0001",
      dec_alu_rf1_log_fcn=>"0000",
      dec_alu_rf1_add_rs0_inv=>(others=>'0'),
      dec_alu_rf1_add_ci=>'0', dec_alu_rf1_is_cmpl=>'0',
      dec_alu_rf1_tw_cmpsel=>"000000",
      dec_ex2_tid=>"0000", dec_ex4_tid=>"0000",
      dec_alu_rf1_mul_recform=>'0', dec_alu_rf1_mul_val=>'0',
      dec_alu_rf1_mul_ret=>'0', dec_alu_rf1_mul_sign=>'0',
      dec_alu_rf1_mul_size=>'0', dec_alu_rf1_mul_imm=>'0',
      fxa_fxb_rf1_div_ctr=>div_ctr,
      dec_alu_rf1_div_val=>instr_v,
      dec_alu_rf1_div_sign=>div_sign,
      dec_alu_rf1_div_size=>div_size,
      dec_alu_rf1_div_extd=>div_extd,
      dec_alu_rf1_div_recform=>'0', dec_alu_ex1_is_cmp=>'0',
      dec_alu_rf1_select_64bmode=>'1',
      fxa_fxb_ex1_hold_ctr_flush=>'0',
      byp_alu_ex1_rs0=>(others=>'0'), byp_alu_ex1_rs1=>(others=>'0'),
      byp_alu_ex1_mulsrc_0=>(others=>'0'), byp_alu_ex1_mulsrc_1=>(others=>'0'),
      byp_alu_ex1_divsrc_0=>d0, byp_alu_ex1_divsrc_1=>d1,
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
      alu_byp_ex1_log_rt=>open, alu_byp_ex2_rt=>open,
      xu_ex1_eff_addr_int=>open, xu_ex2_eff_addr=>open,
      alu_byp_ex5_mul_rt=>open, alu_byp_ex3_div_rt=>div_rt,
      alu_ex2_div_done=>ddone, alu_dec_ex1_ipb_ba=>open,
      alu_dec_ex1_ipb_sz=>open, alu_dec_div_need_hole=>hole,
      alu_ex3_mul_done=>open, alu_ex4_mul_done=>open,
      alu_cpl_ex3_trap_val=>open, alu_byp_ex2_xer=>open,
      alu_byp_ex5_xer_mul=>open, alu_byp_ex3_xer_div=>xer_ov,
      alu_byp_ex2_cr_recform=>open, alu_byp_ex5_cr_mul=>open,
      alu_byp_ex3_cr_div=>open);

  stim : process
    variable got : unsigned(63 downto 0);
    -- sweep div_ctr until DONE; report the quotient
    procedure tc(a, b : natural; sign, size, extd : std_ulogic;
                 ctr : std_ulogic_vector(0 to 7);
                 tag : string; expv : unsigned(63 downto 0)) is
    begin
      -- drive the rf1-mode controls + operands one edge EARLY so ex1_div_size/
      -- sign/extd_q and the ex1_numer/denom comb path settle before div_val
      -- latches (mirrors the pipeline, where decode controls & rf operands are
      -- always aligned at rf1 ahead of the ex1 launch).
      rf_op_a <= std_ulogic_vector(to_unsigned(a,64));
      rf_op_b <= std_ulogic_vector(to_unsigned(b,64));
      div_sign<=sign; div_size<=size; div_extd<=extd; div_ctr<=ctr;
      wait until rising_edge(clk);
      instr_v <= '1';
      wait until rising_edge(clk);   -- rf1 edge: latches div_val+divsrc
      instr_v <= '0';
      -- iterative: wait for div_done, then let the transient settle and read.
      wait until ddone='1';
      for i in 0 to 3 loop wait until rising_edge(clk); end loop;
      got := unsigned(to_stdlogicvector(res));
      -- spacing so a stale div_rt from the next op doesn't bleed in
      for i in 0 to 8 loop wait until rising_edge(clk); end loop;
      assert got = expv
        report tag & " FAIL got=0x"&to_hstring(got)&" exp=0x"&to_hstring(expv)
        severity error;
      if got = expv then report tag & " PASS -> 0x"&to_hstring(got); end if;
    end procedure;
  begin
    report "tb_aludiv: golden xuq_alu divide + generated operand path";
    wait until rising_edge(clk);
    -- recirc_ctr_init decoded from xuq_dec_a TBL_RF0_DEC ROM (per-op):
    --   divw/wu=33  divd/du/divwe/weu=65  divde/deu=129
    -- warm-up: first op of each size-class is discarded (the ex1-latched
    -- div_size/sign controls need a cycle to settle before ex1_numer/denom
    -- compute — the pipeline always drives them correctly, this is a bench
    -- artifact). Run a throwaway divd + divw first.
    tc(4,   2, '1','1','0', "01000001", "warmup divd", to_unsigned(2,64));
    tc(4,   2, '1','0','0', "00100001", "warmup divw", to_unsigned(2,64));
    tc(200, 10,'1','1','0', "01000001", "divd 200/10 ctr=65",to_unsigned(20,64));
    tc(100, 4, '1','1','0', "01000001", "divd 100/4 ctr=65", to_unsigned(25,64));
    tc(96,  8, '1','1','0', "01000001", "divd 96/8 ctr=65",  to_unsigned(12,64));
    tc(100, 4, '1','0','0', "00100001", "divw 100/4 ctr=33", to_unsigned(25,64));
    tc(99,  9, '1','0','0', "00100001", "divw 99/9 ctr=33",  to_unsigned(11,64));
    report "tb_aludiv: div probes done";
    done <= true;
    wait;
  end process;
end architecture;
