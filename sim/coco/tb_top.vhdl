-- tb_top: cocotb-facing toplevel for the a2x_axi full-core scaffold.
--
-- Why this exists: cocotb's Clock() drives clk/clk2x via VPI value writes,
-- and under GHDL-LLVM's VPI those writes do not create VHDL events, so
-- RisingEdge callbacks never fire and simulation time freezes (~44ns).
-- Workaround: generate the clocks natively in VHDL and expose them as
-- output ports. cocotb keeps the AXI-slave/memory-checker role only.
--
-- clk: 8ns period; clk2x: 4ns, phase aligned (both rise together).
-- reset_n held low 80ns then released; thold=0 (tri latches = plain regs).

library ieee; use ieee.std_logic_1164.all;
library work; use work.all;

entity tb_top is
  generic (
    C_M00_AXI_ID_WIDTH   : integer := 4;
    C_M00_AXI_ADDR_WIDTH : integer := 32;
    C_M00_AXI_DATA_WIDTH : integer := 32
  );
  port (
    clk        : out std_logic;
    clk2x      : out std_logic;
    reset_n_o  : out std_logic;                    -- visibility only
    thread_run : out std_logic_vector(0 to 3);     -- visibility only

    m00_axi_awid    : out std_logic_vector(C_M00_AXI_ID_WIDTH-1 downto 0);
    m00_axi_awaddr  : out std_logic_vector(C_M00_AXI_ADDR_WIDTH-1 downto 0);
    m00_axi_awlen   : out std_logic_vector(7 downto 0);
    m00_axi_awsize  : out std_logic_vector(2 downto 0);
    m00_axi_awburst : out std_logic_vector(1 downto 0);
    m00_axi_awlock  : out std_logic;
    m00_axi_awcache : out std_logic_vector(3 downto 0);
    m00_axi_awprot  : out std_logic_vector(2 downto 0);
    m00_axi_awqos   : out std_logic_vector(3 downto 0);
    m00_axi_awuser  : out std_logic_vector(3 downto 0);
    m00_axi_awvalid : out std_logic;
    m00_axi_awready : in  std_logic;
    m00_axi_wdata   : out std_logic_vector(C_M00_AXI_DATA_WIDTH-1 downto 0);
    m00_axi_wstrb   : out std_logic_vector(C_M00_AXI_DATA_WIDTH/8-1 downto 0);
    m00_axi_wlast   : out std_logic;
    m00_axi_wuser   : out std_logic_vector(3 downto 0);
    m00_axi_wvalid  : out std_logic;
    m00_axi_wready  : in  std_logic;
    m00_axi_bid     : in  std_logic_vector(C_M00_AXI_ID_WIDTH-1 downto 0);
    m00_axi_bresp   : in  std_logic_vector(1 downto 0);
    m00_axi_buser   : in  std_logic_vector(3 downto 0);
    m00_axi_bvalid  : in  std_logic;
    m00_axi_bready  : out std_logic;
    m00_axi_arid    : out std_logic_vector(C_M00_AXI_ID_WIDTH-1 downto 0);
    m00_axi_araddr  : out std_logic_vector(C_M00_AXI_ADDR_WIDTH-1 downto 0);
    m00_axi_arlen   : out std_logic_vector(7 downto 0);
    m00_axi_arsize  : out std_logic_vector(2 downto 0);
    m00_axi_arburst : out std_logic_vector(1 downto 0);
    m00_axi_arlock  : out std_logic;
    m00_axi_arcache : out std_logic_vector(3 downto 0);
    m00_axi_arprot  : out std_logic_vector(2 downto 0);
    m00_axi_arqos   : out std_logic_vector(3 downto 0);
    m00_axi_aruser  : out std_logic_vector(3 downto 0);
    m00_axi_arvalid : out std_logic;
    m00_axi_arready : in  std_logic;
    m00_axi_rid     : in  std_logic_vector(C_M00_AXI_ID_WIDTH-1 downto 0);
    m00_axi_rdata   : in  std_logic_vector(C_M00_AXI_DATA_WIDTH-1 downto 0);
    m00_axi_rresp   : in  std_logic_vector(1 downto 0);
    m00_axi_rlast   : in  std_logic;
    m00_axi_ruser   : in  std_logic_vector(3 downto 0);
    m00_axi_rvalid  : in  std_logic;
    m00_axi_rready  : out std_logic
  );
end tb_top;

architecture sim of tb_top is
  signal clk_i    : std_logic := '1';
  signal clk2x_i  : std_logic := '1';
  signal reset_n_i  : std_logic := '0';
  signal tstop_i    : std_logic_vector(0 to 3) := "1111";
begin

  clk       <= clk_i;
  clk2x     <= clk2x_i;
  reset_n_o <= reset_n_i;
  thread_run <= not tstop_i;

  -- 8ns clk / 4ns clk2x, both rising at t=0 mod 8
  clk_gen : process
  begin
    loop
      clk_i   <= '1'; clk2x_i <= '1';   -- 0
      wait for 2 ns;  clk2x_i <= '0';   -- 2
      wait for 2 ns;  clk_i <= '0'; clk2x_i <= '1';  -- 4
      wait for 2 ns;  clk2x_i <= '0';   -- 6
      wait for 2 ns;                    -- 8
    end loop;
  end process;

  -- reset: low 80ns, then release; release thread_stop a few cycles later
  rst_gen : process
  begin
    wait for 80 ns;
    reset_n_i <= '1';
    wait for 40 ns;
    tstop_i <= "0000";
    wait;  -- hold state forever
  end process;

  u_core : entity work.a2x_axi
    generic map (
      C_M00_AXI_ID_WIDTH   => C_M00_AXI_ID_WIDTH,
      C_M00_AXI_ADDR_WIDTH => C_M00_AXI_ADDR_WIDTH,
      C_M00_AXI_DATA_WIDTH => C_M00_AXI_DATA_WIDTH
    )
    port map (
      clk               => clk_i,
      clk2x             => clk2x_i,
      reset_n           => reset_n_i,
      thold             => '0',
      core_id           => x"00",
      thread_stop       => tstop_i,
      thread_running    => open,
      ext_mchk          => "0000",
      ext_checkstop     => '0',
      debug_stop        => '0',
      mchk              => open,
      recov_err         => open,
      checkstop         => open,
      a2l2_axi_err      => open,
      crit_interrupt    => "0000",
      ext_interrupt     => "0000",
      perf_interrupt    => "0000",
      tb_update_enable  => '1',
      tb_update_pulse   => '0',
      scom_sat_id       => "0000",
      scom_dch_in       => '0',
      scom_cch_in       => '0',
      scom_dch_out      => open,
      scom_cch_out      => open,
      flh2l2_gate       => '0',
      hang_pulse        => "0000",
      m00_axi_awid      => m00_axi_awid,
      m00_axi_awaddr    => m00_axi_awaddr,
      m00_axi_awlen     => m00_axi_awlen,
      m00_axi_awsize    => m00_axi_awsize,
      m00_axi_awburst   => m00_axi_awburst,
      m00_axi_awlock    => m00_axi_awlock,
      m00_axi_awcache   => m00_axi_awcache,
      m00_axi_awprot    => m00_axi_awprot,
      m00_axi_awqos     => m00_axi_awqos,
      m00_axi_awuser    => m00_axi_awuser,
      m00_axi_awvalid   => m00_axi_awvalid,
      m00_axi_awready   => m00_axi_awready,
      m00_axi_wdata     => m00_axi_wdata,
      m00_axi_wstrb     => m00_axi_wstrb,
      m00_axi_wlast     => m00_axi_wlast,
      m00_axi_wuser     => m00_axi_wuser,
      m00_axi_wvalid    => m00_axi_wvalid,
      m00_axi_wready    => m00_axi_wready,
      m00_axi_bid       => m00_axi_bid,
      m00_axi_bresp     => m00_axi_bresp,
      m00_axi_buser     => m00_axi_buser,
      m00_axi_bvalid    => m00_axi_bvalid,
      m00_axi_bready    => m00_axi_bready,
      m00_axi_arid      => m00_axi_arid,
      m00_axi_araddr    => m00_axi_araddr,
      m00_axi_arlen     => m00_axi_arlen,
      m00_axi_arsize    => m00_axi_arsize,
      m00_axi_arburst   => m00_axi_arburst,
      m00_axi_arlock    => m00_axi_arlock,
      m00_axi_arcache   => m00_axi_arcache,
      m00_axi_arprot    => m00_axi_arprot,
      m00_axi_arqos     => m00_axi_arqos,
      m00_axi_aruser    => m00_axi_aruser,
      m00_axi_arvalid   => m00_axi_arvalid,
      m00_axi_arready   => m00_axi_arready,
      m00_axi_rid       => m00_axi_rid,
      m00_axi_rdata     => m00_axi_rdata,
      m00_axi_rresp     => m00_axi_rresp,
      m00_axi_rlast     => m00_axi_rlast,
      m00_axi_ruser     => m00_axi_ruser,
      m00_axi_rvalid    => m00_axi_rvalid,
      m00_axi_rready    => m00_axi_rready
    );
end sim;
