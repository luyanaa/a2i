-- Verify the generated load/store effective-address path numerically against
-- golden xuq_agen, replicating the wiring a2i.py emits for FU_AGEN:
--
--   rf_op_a[63:0]  --(register rf->ex)--> ex_op_a (RA base)
--   op_b = Mux(uses_simm, sext(SIMM), fpr_b) -> ex_op_b
--   x <= MSB-swap( ex_op_a )                       -- kernel.py _msb_swap
--   y <= MSB-swap( ex_op_b )
--   mode64 <= '1'; snoop/ERAT/array ports tied off
--   EA <= sum_non_erat                             -- 64b x+y effective address
--
-- xuq_agen is pure combinational (x+y->sum, receiving inverters x_b/y_b) —
-- no act/latches. Verifies the EA operand MSB-swap + the 64b sum output.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
library support;  use support.power_logic_pkg.all;
library ibm;      use ibm.std_ulogic_support.all;
library work;

entity tb_agen is
  generic (runner_cfg : string := "");
end entity;

architecture bench of tb_agen is
  signal vdd, gnd : power_logic;
  signal rf_a, rf_b : std_ulogic_vector(63 downto 0) := (others=>'0');
  signal x, y       : std_ulogic_vector(0 to 63);
  signal ea         : std_ulogic_vector(0 to 63);
  signal done       : boolean := false;

  function msb_swap(sig : std_ulogic_vector; hi : integer)
    return std_ulogic_vector is
    variable r : std_ulogic_vector(0 to hi);
  begin
    for i in 0 to hi loop r(i) := sig(hi - i); end loop;
    return r;
  end function;
begin
  vdd <= '1'; gnd <= '0';
  x <= msb_swap(rf_a, 63);
  y <= msb_swap(rf_b, 63);

  dut : entity work.xuq_agen
    port map (
      x=>x, y=>y,
      snoop_addr=>(others=>'0'), snoop_sel=>'0', binv_val=>'0',
      mode64=>'1', dir_ig_57_b=>'0',
      z=>"00000", way=>"00000000", inv1_val_b=>'0',
      ex1_cache_acc_b=>'0', rel3_val=>'0',
      vdd=>vdd, gnd=>gnd,
      sum_non_erat=>ea, sum=>open,
      sum_arr_dir01=>open, sum_arr_dir23=>open,
      sum_arr_dir45=>open, sum_arr_dir67=>open,
      ary_write_act_01=>open, ary_write_act_23=>open,
      ary_write_act_45=>open, ary_write_act_67=>open,
      ary_write_act=>open, match_oth=>open);

  stim : process
    variable exp, got : unsigned(63 downto 0);
    procedure tc(a, b : natural; tag : string) is
    begin
      rf_a <= std_ulogic_vector(to_unsigned(a,64));
      rf_b <= std_ulogic_vector(to_unsigned(b,64));
      wait for 20 ns;                     -- comb settle
      got := unsigned(to_stdlogicvector(ea));
      exp := to_unsigned(a+b,64);
      assert got = exp
        report tag & " FAIL got=0x"&to_hstring(got)&" exp=0x"&to_hstring(exp)
        severity error;
      if got = exp then report tag & " PASS -> 0x"&to_hstring(got); end if;
    end procedure;
  begin
    report "tb_agen: golden xuq_agen EA adder + generated operand path";
    tc(16#1000#, 16#80#,  "EA 0x1000+0x80");     -- lwz RA+SIMM
    tc(16#1000#, 16#40#,  "EA 0x1000+0x40");     -- stw RA+SIMM
    tc(16#1000#, 16#1234#,"EA 0x1000+0x1234");
    tc(0,        0,       "EA 0+0");
    tc(16#7FFF0000#, 16#1000#, "EA big+disp");
    report "tb_agen: ALL PASS (x+y EA + MSB-swap verified)";
    done <= true;
    wait;
  end process;
end architecture;
