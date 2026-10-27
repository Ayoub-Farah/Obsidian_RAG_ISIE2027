-- SPDX-License-Identifier: MIT
-- Two full-duplex neighbours, a common Aurora USER_CLK, JTAG-only debug.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity obsidian_benchmark_top is
 generic (G_MODE:natural:=2; G_NODES:positive:=3; G_NODE_BASE:natural:=0;
          G_LOCAL_NODES:positive:=1; G_DATA_BYTES:positive:=6; G_REF_BYTES:positive:=2;
          G_RUN_CYCLES:natural:=128; G_ENABLE_LOGICAL_DRIFT:boolean:=false; G_DRIFT_PPB:integer:=2000;G_RUNTIME_CONFIG:boolean:=false;G_FIFO_WORDS:positive:=2048;G_VLINK_FIFO_WORDS:positive:=256);
 port (clk20_vcxo_i,gt_refclk_p_i,gt_refclk_n_i:in std_logic;
       sfp0_txp_o,sfp0_txn_o,sfp1_txp_o,sfp1_txn_o:out std_logic;
       sfp0_rxp_i,sfp0_rxn_i,sfp1_rxp_i,sfp1_rxn_i:in std_logic);
end entity;
architecture rtl of obsidian_benchmark_top is
 component obsidian_dual_aurora is port (
 init_clk_i,rst_i,gt_refclk_p_i,gt_refclk_n_i:in std_logic;
 l_txp_o,l_txn_o,r_txp_o,r_txn_o:out std_logic;
 l_rxp_i,l_rxn_i,r_rxp_i,r_rxn_i:in std_logic;
 user_clk_o:out std_logic;
 channel_up_o,hard_err_o,soft_err_o,frame_err_o:out std_logic_vector(1 downto 0);
 l_tx_data_i,r_tx_data_i:in std_logic_vector(15 downto 0);
 l_tx_keep_i,r_tx_keep_i:in std_logic_vector(1 downto 0);
 l_tx_valid_i,r_tx_valid_i,l_tx_last_i,r_tx_last_i:in std_logic;
 l_tx_ready_o,r_tx_ready_o:out std_logic;
 l_rx_data_o,r_rx_data_o:out std_logic_vector(15 downto 0);
 l_rx_keep_o,r_rx_keep_o:out std_logic_vector(1 downto 0);
 l_rx_valid_o,r_rx_valid_o,l_rx_last_o,r_rx_last_o:out std_logic);
 end component;
 component benchmark_vio is port (clk:in std_logic;
 probe_in0,probe_in1,probe_in2:in std_logic_vector(255 downto 0);
 probe_in3:in std_logic_vector(63 downto 0);probe_in4:in std_logic_vector(1 downto 0);probe_in5:in std_logic_vector(5 downto 0);
 probe_out0,probe_out1,probe_out2:out std_logic_vector(0 downto 0);probe_out3:out std_logic_vector(7 downto 0));end component;
 component runtime_vio is port (clk:in std_logic;
 probe_in0,probe_in1,probe_in2:in std_logic_vector(255 downto 0);
 probe_in3:in std_logic_vector(63 downto 0);probe_in4:in std_logic_vector(1 downto 0);probe_in5:in std_logic_vector(5 downto 0);
 probe_out0,probe_out1,probe_out2:out std_logic_vector(0 downto 0);probe_out3:out std_logic_vector(7 downto 0);probe_out4:out std_logic_vector(31 downto 0));end component;
 component benchmark_ila is port (clk:in std_logic;
 probe0:in std_logic_vector(255 downto 0);probe1:in std_logic_vector(63 downto 0);
 probe2:in std_logic_vector(95 downto 0));end component;
 signal config_word:std_logic_vector(31 downto 0):=(others=>'0');
 signal init_clk,init_reset,mmcm_locked,user_clk,core_reset:std_logic;
 signal reset_pipe:std_logic_vector(2 downto 0):=(others=>'1');
 signal vio_reset,vio_start,vio_stop:std_logic_vector(0 downto 0);
 signal channel_up,hard_err,soft_err,frame_err:std_logic_vector(1 downto 0);
 signal status:std_logic_vector(255 downto 0);signal raw:std_logic_vector(63 downto 0);
 signal log_addr:std_logic_vector(7 downto 0);signal log_data:std_logic_vector(511 downto 0);
 signal ltx,rtx,lrx,rrx:std_logic_vector(15 downto 0);
 signal ltk,rtk,lrk,rrk:std_logic_vector(1 downto 0);
 signal ltv,rtv,lrv,rrv,ltl,rtl,lrl,rrl,ltr,rtr:std_logic;
 signal stream_probe:std_logic_vector(95 downto 0);
 attribute ASYNC_REG:string;
 attribute ASYNC_REG of reset_pipe:signal is "TRUE";
begin
 u_clock:entity work.board_clock_reset_manager port map(clk20_vcxo_i,init_clk,init_reset,mmcm_locked);
 u_optical:obsidian_dual_aurora port map(
 init_clk_i=>init_clk,rst_i=>init_reset,gt_refclk_p_i=>gt_refclk_p_i,gt_refclk_n_i=>gt_refclk_n_i,
 l_txp_o=>sfp0_txp_o,l_txn_o=>sfp0_txn_o,r_txp_o=>sfp1_txp_o,r_txn_o=>sfp1_txn_o,
 l_rxp_i=>sfp0_rxp_i,l_rxn_i=>sfp0_rxn_i,r_rxp_i=>sfp1_rxp_i,r_rxn_i=>sfp1_rxn_i,user_clk_o=>user_clk,
 channel_up_o=>channel_up,hard_err_o=>hard_err,soft_err_o=>soft_err,frame_err_o=>frame_err,
 l_tx_data_i=>ltx,r_tx_data_i=>rtx,l_tx_keep_i=>ltk,r_tx_keep_i=>rtk,
 l_tx_valid_i=>ltv,r_tx_valid_i=>rtv,l_tx_last_i=>ltl,r_tx_last_i=>rtl,
 l_tx_ready_o=>ltr,r_tx_ready_o=>rtr,l_rx_data_o=>lrx,r_rx_data_o=>rrx,
 l_rx_keep_o=>lrk,r_rx_keep_o=>rrk,l_rx_valid_o=>lrv,r_rx_valid_o=>rrv,l_rx_last_o=>lrl,r_rx_last_o=>rrl);
 process(user_clk,init_reset) begin
  if init_reset='1' then reset_pipe<=(others=>'1');
  elsif rising_edge(user_clk) then reset_pipe<=reset_pipe(1 downto 0)&'0'; end if;
 end process;
 core_reset<=reset_pipe(2) or vio_reset(0);
 u_benchmark:entity work.benchmark_system
 generic map(G_MODE=>G_MODE,G_NODES=>G_NODES,G_NODE_BASE=>G_NODE_BASE,
 G_LOCAL_NODES=>G_LOCAL_NODES,G_DATA_BYTES=>G_DATA_BYTES,G_REF_BYTES=>G_REF_BYTES,
 G_RUN_CYCLES=>G_RUN_CYCLES,G_ENABLE_LOGICAL_DRIFT=>G_ENABLE_LOGICAL_DRIFT,G_DRIFT_PPB=>G_DRIFT_PPB,G_RUNTIME_CONFIG=>G_RUNTIME_CONFIG,G_FIFO_WORDS=>G_FIFO_WORDS,G_VLINK_FIFO_WORDS=>G_VLINK_FIFO_WORDS)
 port map(clk_i=>user_clk,rst_i=>core_reset,start_i=>vio_start(0),stop_i=>vio_stop(0),
 links_up_i=>channel_up(0) and channel_up(1),link_fault_i=>hard_err(0) or hard_err(1) or frame_err(0) or frame_err(1),
 left_rx_data_i=>lrx,left_rx_keep_i=>lrk,left_rx_valid_i=>lrv,left_rx_last_i=>lrl,
 left_tx_data_o=>ltx,left_tx_keep_o=>ltk,left_tx_valid_o=>ltv,left_tx_last_o=>ltl,left_tx_ready_i=>ltr,
 right_rx_data_i=>rrx,right_rx_keep_i=>rrk,right_rx_valid_i=>rrv,right_rx_last_i=>rrl,
 right_tx_data_o=>rtx,right_tx_keep_o=>rtk,right_tx_valid_o=>rtv,right_tx_last_o=>rtl,right_tx_ready_i=>rtr,
 status_o=>status,raw_counter_o=>raw,log_addr_i=>log_addr,log_data_o=>log_data,
 config_mode_i=>to_integer(unsigned(config_word(1 downto 0))),config_nodes_i=>to_integer(unsigned(config_word(7 downto 2))),
 config_base_i=>to_integer(unsigned(config_word(13 downto 8))),config_local_i=>to_integer(unsigned(config_word(19 downto 14))));
 static_debug:if not G_RUNTIME_CONFIG generate
 u_vio:benchmark_vio port map(clk=>user_clk,probe_in0=>status,probe_in1=>log_data(255 downto 0),
 probe_in2=>log_data(511 downto 256),probe_in3=>raw,probe_in4=>channel_up,probe_in5=>hard_err&soft_err&frame_err,
 probe_out0=>vio_reset,probe_out1=>vio_start,probe_out2=>vio_stop,probe_out3=>log_addr);
 end generate;
 dynamic_debug:if G_RUNTIME_CONFIG generate
 u_vio:runtime_vio port map(clk=>user_clk,probe_in0=>status,probe_in1=>log_data(255 downto 0),
 probe_in2=>log_data(511 downto 256),probe_in3=>raw,probe_in4=>channel_up,probe_in5=>hard_err&soft_err&frame_err,
 probe_out0=>vio_reset,probe_out1=>vio_start,probe_out2=>vio_stop,probe_out3=>log_addr,probe_out4=>config_word);
 end generate;
 -- Every 24-bit chunk is data16,keep2,valid,last,ready,zero3.
 -- RX has no ready: captured valid words must always enter the protocol FIFO.
 stream_probe <= rrx&rrk&rrv&rrl&'1'&"000" & lrx&lrk&lrv&lrl&'1'&"000" &
                 rtx&rtk&rtv&rtl&rtr&"000" & ltx&ltk&ltv&ltl&ltr&"000";
 static_ila:if not G_RUNTIME_CONFIG generate
 u_ila:benchmark_ila port map(clk=>user_clk,probe0=>status,probe1=>raw,probe2=>stream_probe);
 end generate;
end architecture;
