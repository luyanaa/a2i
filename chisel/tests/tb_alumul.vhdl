-- Probe + verify the GPR multiply path on golden xuq_alu (the full FXU, which
-- wraps xuq_alu_mult), replicating the wiring a2i.py emits for a mul op:
--
--   rf_op_a/b[63:0] --(register rf->ex)--> ex_op_a/b[63:0]
--   byp_alu_ex1_mulsrc_0/1 <= MSB-swap( ex_op_a/b )   -- ex1-comb operands
--   dec_alu_rf1_mul_{val,ret,sign,size,imm} <= rf1-latched controls
--   result <= alu_byp_ex5_mul_rt                       -- 64b product (ex5)
--
-- xuq_alu_mult is a 5-stage Booth pipeline: mulsrc is read comb at ex1 and
-- re-registered ex1->ex2; mul_val/size/sign/ret/imm latch rf1->ex1 on the act.
-- The bench holds mul_val for one rf1 edge, drives operands at ex1, then
-- watches alu_byp_ex5_mul_rt + alu_ex3/ex4_mul_done for the result cycle.
--
-- Semantics (from xuq_dec_b.vhdl): mul_size 0=32x32(mullw) 1=64x64(mulld/mulli);
-- mul_sign 1=signed 0=unsigned; mul_imm 1=16b SE immediate; mul_ret 1=high half.
--
-- RESULT-CAPTURE CONTRACT (measured in this bench):
--   mul_size=0 (mullw/mulhw/mulhwu): ex5 product, stable ~5 edges after rf1.
--   mul_size=1 (mulld/mulhd/mulli): 64x64 recirculates through the ex2_mulsrc
--     32b-swap network; product is a ~1-cycle pulse right after the
--     alu_ex4_mul_done flag — capture on (done4 edge + 2). The pipeline WB must
--     latch mul_rt on mul_done, not read a fixed-cycle launch value.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
library support;  use support.power_logic_pkg.all;
library ibm;      use ibm.std_ulogic_support.all;
library tri;      use tri.tri_latches_pkg.all;
library work;

entity tb_alumul is
  generic (runner_cfg : string := "");
end entity;

architecture bench of tb_alumul is
  constant expand_type : integer := 1;
  signal clk, clk2x    : std_ulogic := '0';
  signal nclk          : clk_logic;
  signal vdd, gnd      : power_logic;

  signal rf_op_a, rf_op_b : std_ulogic_vector(63 downto 0) := (others=>'0');
  signal instr_v          : std_ulogic := '0';
  signal mul_ret          : std_ulogic := '0';
  signal mul_sign         : std_ulogic := '1';
  signal mul_size         : std_ulogic := '0';   -- 0=32x32 mullw default
  signal mul_imm          : std_ulogic := '0';
  signal res              : std_ulogic_vector(0 to 63);
  signal done3, done4     : std_ulogic;

  signal ex_op_a, ex_op_b : std_ulogic_vector(63 downto 0) := (others=>'0');
  signal m0, m1           : std_ulogic_vector(0 to 63);
  signal mul_rt           : std_ulogic_vector(0 to 63);
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
      if unsigned(to_stdlogicvector(mul_rt)) /= 0 then
        report "CYC" & integer'image(cyc) &
               " mul_rt=0x" & to_hstring(unsigned(to_stdlogicvector(mul_rt)));
      end if;
      if done3='1' or done4='1' then
        report "DONE CYC" & integer'image(cyc) &
               " done3=" & std_ulogic'image(done3) &
               " done4=" & std_ulogic'image(done4);
      end if;
    end if;
  end process;

  m0 <= msb_swap(ex_op_a, 63);
  m1 <= msb_swap(ex_op_b, 63);
  res <= mul_rt;

  dut : entity work.xuq_alu
    generic map (expand_type => expand_type)
    port map (
      nclk=>nclk, vdd=>vdd, gnd=>gnd,
      d_mode_dc=>'0', delay_lclkr_dc=>'0', mpw1_dc_b=>'0', mpw2_dc_b=>'0',
      func_sl_force=>'0', func_sl_thold_0_b=>'1',
      sg_0=>'0', scan_in=>"00", scan_out=>open,
      spr_msr_cm=>"0001",
      dec_alu_rf1_act=>instr_v, dec_alu_ex1_act=>instr_v,
      dec_alu_rf1_sel=>"0001",                 -- sel != 0 -> not the log path
      dec_alu_rf1_log_fcn=>"0000",
      dec_alu_rf1_add_rs0_inv=>(others=>'0'),
      dec_alu_rf1_add_ci=>'0', dec_alu_rf1_is_cmpl=>'0',
      dec_alu_rf1_tw_cmpsel=>"000000",
      dec_ex2_tid=>"0000", dec_ex4_tid=>"0000",
      dec_alu_rf1_mul_recform=>'0',
      dec_alu_rf1_mul_val=>instr_v,
      dec_alu_rf1_mul_ret=>mul_ret,
      dec_alu_rf1_mul_sign=>mul_sign,
      dec_alu_rf1_mul_size=>mul_size,
      dec_alu_rf1_mul_imm=>mul_imm,
      fxa_fxb_rf1_div_ctr=>"00000000",
      dec_alu_rf1_div_val=>'0', dec_alu_rf1_div_sign=>'0',
      dec_alu_rf1_div_size=>'0', dec_alu_rf1_div_extd=>'0',
      dec_alu_rf1_div_recform=>'0', dec_alu_ex1_is_cmp=>'0',
      dec_alu_rf1_select_64bmode=>'1',
      fxa_fxb_ex1_hold_ctr_flush=>'0',
      byp_alu_ex1_rs0=>(others=>'0'), byp_alu_ex1_rs1=>(others=>'0'),
      byp_alu_ex1_mulsrc_0=>m0, byp_alu_ex1_mulsrc_1=>m1,
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
      alu_byp_ex1_log_rt=>open, alu_byp_ex2_rt=>open,
      xu_ex1_eff_addr_int=>open, xu_ex2_eff_addr=>open,
      alu_byp_ex5_mul_rt=>mul_rt, alu_byp_ex3_div_rt=>open,
      alu_ex2_div_done=>open, alu_dec_ex1_ipb_ba=>open,
      alu_dec_ex1_ipb_sz=>open, alu_dec_div_need_hole=>open,
      alu_ex3_mul_done=>done3, alu_ex4_mul_done=>done4,
      alu_cpl_ex3_trap_val=>open, alu_byp_ex2_xer=>open,
      alu_byp_ex5_xer_mul=>open, alu_byp_ex3_xer_div=>open,
      alu_byp_ex2_cr_recform=>open, alu_byp_ex5_cr_mul=>open,
      alu_byp_ex3_cr_div=>open);

  stim : process
    variable got : unsigned(63 downto 0);
    procedure tc(a, b : natural; sign, size, ret, imm : std_ulogic;
                 tag : string; expv : unsigned(63 downto 0); hold : integer := 1) is
    begin
      rf_op_a <= std_ulogic_vector(to_unsigned(a,64));
      rf_op_b <= std_ulogic_vector(to_unsigned(b,64));
      mul_sign<=sign; mul_size<=size; mul_ret<=ret; mul_imm<=imm;
      instr_v <= '1';
      wait until rising_edge(clk);       -- rf1 edge: latches controls + operands
      instr_v <= '0';
      -- keep operands stable for `hold` extra cycles so the 64x64 Booth
      -- recirculation (ex2_mulsrc swap network) re-reads them correctly.
      for h in 2 to hold loop wait until rising_edge(clk); end loop;
      -- For 32x32: ex5 product is stable ~5 edges after rf1. For 64x64 the
      -- product is a 1-cycle pulse right after the ex4 done flag — wait for
      -- done4 then read the next edge.
      if size='1' then
        wait until done4='1';
        wait until rising_edge(clk);
        wait until rising_edge(clk);
      else
        for i in 0 to 4 loop wait until rising_edge(clk); end loop;
      end if;
      got := unsigned(to_stdlogicvector(res));
      assert got = expv
        report tag & " FAIL got=0x"&to_hstring(got)&" exp=0x"&to_hstring(expv)
        severity error;
      if got = expv then report tag & " PASS -> 0x"&to_hstring(got); end if;
    end procedure;
  begin
    report "tb_alumul: golden xuq_alu mul path + generated operand path";
    wait until rising_edge(clk);
    -- mullw: 32x32 signed low-half product (mul_size=0, sign=1, ret=0)
    tc(3,   4,   '1','0','0','0', "mullw 3*4",   to_unsigned(12,64));
    tc(6,   7,   '1','0','0','0', "mullw 6*7",   to_unsigned(42,64));
    tc(16#1234#, 16#10#, '1','0','0','0', "mullw 0x1234*0x10", to_unsigned(16#12340#,64));
    -- mulhw: high 32 of the 32x32 signed product (mul_ret=1, size=0, sign=1)
    -- 0x10000 * 0x10000 = 0x1_0000_0000 -> high word = 1
    tc(16#10000#, 16#10000#, '1','0','1','0', "mulhw 2^16*2^16", to_unsigned(1,64));
    -- mulhwu: high 32, unsigned (sign=0)
    tc(16#10000#, 16#10000#, '0','0','1','0', "mulhwu 2^16*2^16", to_unsigned(1,64));
    -- mulld/mulli (mul_size=1, 64x64): product is a 1-cycle pulse right after
    -- the ex4 done flag (later than the 32x32 ops, extra Booth recirculation).
    tc(6,   7,   '1','1','0','0', "mulld 6*7",   to_unsigned(42,64), 1);
    tc(3,   5,   '1','1','0','0', "mulld 3*5",   to_unsigned(15,64), 1);
    tc(16#100#, 16#20#, '1','1','0','0', "mulld 0x100*0x20", to_unsigned(16#2000#,64), 1);
    -- mulli: mul_imm=1 (operand B = the 16b SE immediate; in the bench we just
    -- drive a value as mulsrc_1 the same way — mul_imm only affects retsel)
    tc(9,   12,  '1','1','0','1', "mulli 9*12",  to_unsigned(108,64), 1);
    report "tb_alumul: mul probes done";
    done <= true;
    wait;
  end process;
end architecture;
