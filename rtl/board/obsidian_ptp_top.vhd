-- Dedicated PTP-only image. GPIOs are reserved for local epoch markers.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity obsidian_ptp_top is
  generic(G_CAPACITY:positive:=1;G_MAX_NODES:positive:=3);
  port(clk20_vcxo_i,gt_refclk_p_i,gt_refclk_n_i:in std_logic;
    sfp0_txp_o,sfp0_txn_o,sfp1_txp_o,sfp1_txn_o:out std_logic;
    sfp0_rxp_i,sfp0_rxn_i,sfp1_rxp_i,sfp1_rxn_i:in std_logic;
    test_ref_m1_o,test_obs_o:out std_logic);
end;
architecture rtl of obsidian_ptp_top is
  component obsidian_dual_aurora is port(
    init_clk_i,rst_i,gt_refclk_p_i,gt_refclk_n_i:in std_logic;
    l_txp_o,l_txn_o,r_txp_o,r_txn_o:out std_logic;
    l_rxp_i,l_rxn_i,r_rxp_i,r_rxn_i:in std_logic;user_clk_o:out std_logic;
    channel_up_o,hard_err_o,soft_err_o,frame_err_o:out std_logic_vector(1 downto 0);
    l_tx_data_i,r_tx_data_i:in std_logic_vector(15 downto 0);
    l_tx_keep_i,r_tx_keep_i:in std_logic_vector(1 downto 0);
    l_tx_valid_i,r_tx_valid_i,l_tx_last_i,r_tx_last_i:in std_logic;
    l_tx_ready_o,r_tx_ready_o:out std_logic;
    l_rx_data_o,r_rx_data_o:out std_logic_vector(15 downto 0);
    l_rx_keep_o,r_rx_keep_o:out std_logic_vector(1 downto 0);
    l_rx_valid_o,r_rx_valid_o,l_rx_last_o,r_rx_last_o:out std_logic);end component;
  component ptp_vio is port(clk:in std_logic;
    probe_in0:in std_logic_vector(255 downto 0);
    probe_in1,probe_in2,probe_in3:in std_logic_vector(63 downto 0);
    probe_in4:in std_logic_vector(1 downto 0);probe_in5:in std_logic_vector(5 downto 0);
    probe_out0:out std_logic_vector(0 downto 0);probe_out1:out std_logic_vector(15 downto 0);
    probe_out2:out std_logic_vector(63 downto 0);
    probe_out3,probe_out4,probe_out5,probe_out6:out std_logic_vector(0 downto 0);
    probe_out7:out std_logic_vector(1 downto 0);probe_out8:out std_logic_vector(15 downto 0);
    probe_out9,probe_out10,probe_out11,probe_out12:out std_logic_vector(0 downto 0));end component;
  signal init_clk,init_reset,locked,user_clk,core_reset:std_logic;
  signal reset_pipe:std_logic_vector(2 downto 0):=(others=>'1');
  attribute ASYNC_REG:string;attribute ASYNC_REG of reset_pipe:signal is "TRUE";
  signal reset_cmd,write_cmd,commit_cmd,start_cmd,stop_cmd,obs_apply,obs_enable,snapshot_cmd,ack_cmd:std_logic_vector(0 downto 0);
  signal address,obs_shadow:std_logic_vector(15 downto 0);signal role:std_logic_vector(1 downto 0);
  signal write_data,read_data,config_id,obs_status:std_logic_vector(63 downto 0);
  signal status:std_logic_vector(255 downto 0);
  signal channel_up,hard_err,soft_err,frame_err:std_logic_vector(1 downto 0);
  signal ld,rd,lr,rr:std_logic_vector(15 downto 0);signal lk,rk,lrk,rrk:std_logic_vector(1 downto 0);
  signal lv,rv,ll,rl,lready,rready,lrv,rrv,lrl,rrl:std_logic;

begin
  u_clock:entity work.board_clock_reset_manager port map(clk20_vcxo_i,init_clk,init_reset,locked);
  u_optical:obsidian_dual_aurora port map(init_clk,init_reset,gt_refclk_p_i,gt_refclk_n_i,
    sfp0_txp_o,sfp0_txn_o,sfp1_txp_o,sfp1_txn_o,sfp0_rxp_i,sfp0_rxn_i,sfp1_rxp_i,sfp1_rxn_i,user_clk,
    channel_up,hard_err,soft_err,frame_err,ld,rd,lk,rk,lv,rv,ll,rl,lready,rready,lr,rr,lrk,rrk,lrv,rrv,lrl,rrl);
  process(user_clk,init_reset) begin
    if init_reset='1' then reset_pipe<=(others=>'1');elsif rising_edge(user_clk) then reset_pipe<=reset_pipe(1 downto 0)&'0';end if;
  end process;
  core_reset<=reset_pipe(2) or reset_cmd(0);
  u_ptp:entity work.ptp_emulation_system generic map(G_CAPACITY,G_MAX_NODES)
    port map(user_clk,core_reset,channel_up(0) and channel_up(1),unsigned(address),write_data,
      write_cmd(0),commit_cmd(0),start_cmd(0),stop_cmd(0),unsigned(role),unsigned(obs_shadow),obs_apply(0),obs_enable(0),snapshot_cmd(0),ack_cmd(0),
      read_data,status,obs_status,config_id,test_ref_m1_o,test_obs_o,
      lr,rr,lrk,rrk,lrv,lrl,rrv,rrl,ld,rd,lk,rk,lv,ll,rv,rl,lready,rready);
  u_vio:ptp_vio port map(user_clk,status,read_data,config_id,obs_status,channel_up,hard_err&soft_err&frame_err,
    reset_cmd,address,write_data,write_cmd,commit_cmd,start_cmd,stop_cmd,role,obs_shadow,obs_apply,obs_enable,snapshot_cmd,ack_cmd);
end;
