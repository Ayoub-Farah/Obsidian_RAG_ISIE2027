library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.benchmark_pkg.all;

-- E0 with LOCAL_NODES=1; E1 with independent protocol nodes/links per segment.
-- All nodes on one FPGA share a physical clock. Optional E2 injects logical drift only.
entity benchmark_system is
 generic(G_MODE:natural:=2;G_NODES:positive:=3;G_NODE_BASE:natural:=0;
 G_LOCAL_NODES:positive:=1;G_DATA_BYTES:positive:=6;G_REF_BYTES:positive:=2;
 G_PERIOD_CYCLES:positive:=6250;G_ARM_DELAY_CYCLES:positive:=312500;G_RUN_CYCLES:natural:=128;
 G_ENABLE_LOGICAL_DRIFT:boolean:=false;G_DRIFT_PPB:integer:=2000;G_FIFO_WORDS:positive:=2048;
 G_MAX_FRAME_BYTES:positive:=4096;G_VLINK_LATENCY:positive:=37;
 G_VLINK_FIFO_WORDS:positive:=256;G_RUNTIME_CONFIG:boolean:=false);
 port(clk_i,rst_i,start_i,stop_i,links_up_i,link_fault_i:in std_logic;
 left_rx_data_i:in std_logic_vector(15 downto 0);left_rx_keep_i:in std_logic_vector(1 downto 0);left_rx_valid_i,left_rx_last_i:in std_logic;
 left_tx_data_o:out std_logic_vector(15 downto 0);left_tx_keep_o:out std_logic_vector(1 downto 0);left_tx_valid_o,left_tx_last_o:out std_logic;left_tx_ready_i:in std_logic;
 right_rx_data_i:in std_logic_vector(15 downto 0);right_rx_keep_i:in std_logic_vector(1 downto 0);right_rx_valid_i,right_rx_last_i:in std_logic;
 right_tx_data_o:out std_logic_vector(15 downto 0);right_tx_keep_o:out std_logic_vector(1 downto 0);right_tx_valid_o,right_tx_last_o:out std_logic;right_tx_ready_i:in std_logic;
 status_o:out std_logic_vector(255 downto 0);raw_counter_o:out std_logic_vector(63 downto 0);
 log_addr_i:in std_logic_vector(7 downto 0);log_data_o:out std_logic_vector(511 downto 0);
 config_mode_i:in natural range 0 to 3:=G_MODE;
 config_nodes_i:in natural range 0 to 63:=G_NODES;
 config_base_i:in natural range 0 to 63:=G_NODE_BASE;
 config_local_i:in natural range 0 to 63:=G_LOCAL_NODES);
end;
architecture rtl of benchmark_system is
 subtype bits_t is std_logic_vector(G_LOCAL_NODES-1 downto 0);
 type time_array_t is array(natural range <>) of std_logic_vector(63 downto 0);
 signal filtered_data,filter_hw:word_array_t(0 to G_LOCAL_NODES-1);
 signal filtered_keep:keep_array_t(0 to G_LOCAL_NODES-1);
 signal filtered_valid,filtered_last,filter_empty,filter_overflow:bits_t;
 signal lr_data,rr_data,lt_data,rt_data,dt_data,srt_data:word_array_t(0 to G_LOCAL_NODES-1);
 signal lr_keep,rr_keep,lt_keep,rt_keep,dt_keep,srt_keep:keep_array_t(0 to G_LOCAL_NODES-1);
 signal lr_valid,lr_last,rr_valid,rr_last,lt_valid,lt_last,rt_valid,rt_last:bits_t;
 signal lt_ready,rt_ready,dt_valid,dt_last,dt_ready,dr_ready,srt_valid,srt_last,srt_ready:bits_t;
 signal launch,engine_start,running,locked,mgmt,syncerr,useful,drained,err,ftx,frx:bits_t;
 signal transport_error,link_error,previous_links,node_rst:std_logic:='0';
 signal channel_resets:unsigned(31 downto 0):=(others=>'0');
 signal forward_empty,reverse_empty:bits_t:=(others=>'1');
 signal cycles,crcs,misses:u32_array_t(0 to G_LOCAL_NODES-1);
 signal hw:word_array_t(0 to G_LOCAL_NODES-1);
 signal raws,logical_times,offsets,delays:time_array_t(0 to G_LOCAL_NODES-1);
 signal idle,enabled,node_reset,raw_useful,raw_drained,raw_err,raw_running,raw_locked,raw_syncerr,returned:bits_t;
 signal engine_lt_data,engine_rt_data:word_array_t(0 to G_LOCAL_NODES-1);
 signal engine_lt_keep,engine_rt_keep:keep_array_t(0 to G_LOCAL_NODES-1);
 signal engine_lt_valid,engine_lt_last,engine_rt_valid,engine_rt_last:bits_t;
 signal config_valid:std_logic:='1';
 signal cfg_nodes:positive range 1 to G_NODES:=G_NODES;
 signal cfg_local:positive range 1 to G_LOCAL_NODES:=G_LOCAL_NODES;
 signal cfg_base:natural range 0 to G_NODES-1:=G_NODE_BASE;
 signal cfg_mode:natural range 0 to 2:=G_MODE;
 type id_array_t is array(natural range <>) of natural range 0 to G_NODES-1;
 signal node_ids:id_array_t(0 to G_LOCAL_NODES-1);
 signal seen_return:std_logic:='0';
 signal treturn:unsigned(63 downto 0):=(others=>'1');
 signal capempty_l,capempty_r,capoverflow_l,capoverflow_r:std_logic;
 signal caphw_l,caphw_r:std_logic_vector(15 downto 0);
 signal all_useful,all_drained,any_error,all_locked:std_logic;
 signal raw:unsigned(63 downto 0):=(others=>'0');
 signal measuring,recorded,seen_useful,seen_tx:std_logic:='0';
 signal t0,tuse,ttx:unsigned(63 downto 0):=(others=>'0');
 signal deadline_count,sequence_id:unsigned(31 downto 0):=(others=>'0');
 signal log_wr:natural range 0 to 255:=0;
 type log_t is array(0 to 255) of std_logic_vector(511 downto 0);
 signal journal:log_t;
 signal log_read:std_logic_vector(511 downto 0);
 signal summary:std_logic_vector(255 downto 0):=(others=>'0');
 function node_drift(i:natural) return integer is
 begin if not G_ENABLE_LOGICAL_DRIFT or G_NODE_BASE+i=0 then return 0;
 elsif (G_NODE_BASE+i) mod 2=0 then return G_DRIFT_PPB;else return -G_DRIFT_PPB;end if;end;
 component rag_node is
 generic(G_MODE:natural:=2;G_NODES:positive:=3;G_NODE_ID:natural:=0;G_DATA_BYTES:positive:=6;G_REF_BYTES:positive:=2;G_FIFO_WORDS:positive:=2048;G_MAX_FRAME_BYTES:positive:=4096);
 port(clk_i,rst_i,start_i:in std_logic;cycle_id_i:in std_logic_vector(31 downto 0);
 rx_data_i:in std_logic_vector(15 downto 0);rx_keep_i:in std_logic_vector(1 downto 0);rx_valid_i,rx_last_i:in std_logic;rx_ready_o:out std_logic;
 tx_data_o:out std_logic_vector(15 downto 0);tx_keep_o:out std_logic_vector(1 downto 0);tx_valid_o,tx_last_o:out std_logic;tx_ready_i:in std_logic;
 useful_o,drained_o,error_o:out std_logic;crc_errors_o:out std_logic_vector(31 downto 0);fifo_highwater_o:out std_logic_vector(15 downto 0);first_tx_o,first_rx_o:out std_logic;
 data_addr_i:in std_logic_vector(15 downto 0);data_byte_o:out std_logic_vector(7 downto 0));
 end component;
 component aggregate_node is
 generic(G_MODE:natural:=3;G_NODES:positive:=3;G_NODE_ID:natural:=0;G_DATA_BYTES:positive:=6;G_REF_BYTES:positive:=2;G_FIFO_WORDS:positive:=2048;G_MAX_FRAME_BYTES:positive:=4096);
 port(clk_i,rst_i,start_i:in std_logic;cycle_id_i:in std_logic_vector(31 downto 0);
 rx_data_i:in std_logic_vector(15 downto 0);rx_keep_i:in std_logic_vector(1 downto 0);rx_valid_i,rx_last_i:in std_logic;rx_ready_o:out std_logic;
 tx_data_o:out std_logic_vector(15 downto 0);tx_keep_o:out std_logic_vector(1 downto 0);tx_valid_o,tx_last_o:out std_logic;tx_ready_i:in std_logic;
 useful_o,drained_o,error_o:out std_logic;crc_errors_o:out std_logic_vector(31 downto 0);fifo_highwater_o:out std_logic_vector(15 downto 0);first_tx_o,first_rx_o:out std_logic;
 data_addr_i:in std_logic_vector(15 downto 0);data_byte_o:out std_logic_vector(7 downto 0));
 end component;
 begin
 -- Configuration is sampled only while reset is asserted. A running campaign
 -- therefore cannot be rewired by changing VIO values.
 dynamic_config:if G_RUNTIME_CONFIG generate
 process(clk_i) begin if rising_edge(clk_i) then
  if rst_i='1' then
   if config_mode_i/=1 and config_mode_i<=2 and config_nodes_i>=3 and config_nodes_i<=G_NODES and
      config_local_i>=1 and config_local_i<=G_LOCAL_NODES and config_base_i+config_local_i<=config_nodes_i then
    cfg_nodes<=config_nodes_i;cfg_local<=config_local_i;cfg_base<=config_base_i;cfg_mode<=config_mode_i;config_valid<='1';
   else config_valid<='0';end if;
  end if;
 end if;end process;
 end generate;
 node_rst<=rst_i or link_fault_i or not config_valid;
 assert G_NODE_BASE+G_LOCAL_NODES<=G_NODES report "Segment IDs exceed N" severity failure;
 assert G_NODES*G_DATA_BYTES<=65536 report "Data address space overflow" severity failure;
 cap_l:entity work.aurora_rx_capture generic map(G_FIFO_WORDS) port map(clk_i,node_rst,left_rx_data_i,left_rx_keep_i,left_rx_valid_i,left_rx_last_i,lr_data(0),lr_keep(0),lr_valid(0),lr_last(0),'1',capempty_l,capoverflow_l,caphw_l);
 cap_r:entity work.aurora_rx_capture generic map(G_FIFO_WORDS) port map(clk_i,node_rst,right_rx_data_i,right_rx_keep_i,right_rx_valid_i,right_rx_last_i,rr_data(G_LOCAL_NODES-1),rr_keep(G_LOCAL_NODES-1),rr_valid(G_LOCAL_NODES-1),rr_last(G_LOCAL_NODES-1),'1',capempty_r,capoverflow_r,caphw_r);
 left_tx_data_o<=lt_data(0);left_tx_keep_o<=lt_keep(0);left_tx_valid_o<=lt_valid(0);left_tx_last_o<=lt_last(0);lt_ready(0)<=left_tx_ready_i;
 right_tx_data_o<=rt_data(G_LOCAL_NODES-1);right_tx_keep_o<=rt_keep(G_LOCAL_NODES-1);right_tx_valid_o<=rt_valid(G_LOCAL_NODES-1);right_tx_last_o<=rt_last(G_LOCAL_NODES-1);rt_ready(G_LOCAL_NODES-1)<=right_tx_ready_i;
 nodes:for i in 0 to G_LOCAL_NODES-1 generate
  enabled(i)<='1' when i<cfg_local else '0';
  node_ids(i)<=cfg_base+i when i<cfg_local else 0;
  node_reset(i)<=node_rst or not enabled(i);
  useful(i)<=raw_useful(i) or not enabled(i);drained(i)<=raw_drained(i) or not enabled(i);
  running(i)<=raw_running(i) or not enabled(i);locked(i)<=raw_locked(i) or not enabled(i);
  err(i)<=raw_err(i) and enabled(i);syncerr(i)<=raw_syncerr(i) and enabled(i);
  -- Inactive positions are wire bypasses in both directions, with no virtual
  -- link delay or emulated endpoint inserted into the active ring.
  lt_data(i)<=engine_lt_data(i) when enabled(i)='1' else rr_data(i);
  lt_keep(i)<=engine_lt_keep(i) when enabled(i)='1' else rr_keep(i);
  lt_valid(i)<=engine_lt_valid(i) when enabled(i)='1' else rr_valid(i);
  lt_last(i)<=engine_lt_last(i) when enabled(i)='1' else rr_last(i);
  rt_data(i)<=engine_rt_data(i) when enabled(i)='1' else lr_data(i);
  rt_keep(i)<=engine_rt_keep(i) when enabled(i)='1' else lr_keep(i);
  rt_valid(i)<=engine_rt_valid(i) when enabled(i)='1' else lr_valid(i);
  rt_last(i)<=engine_rt_last(i) when enabled(i)='1' else lr_last(i);
  idle(i)<=drained(i) or not running(i);
  sync:entity work.sync_system generic map(G_NODE_ID=>G_NODE_BASE+i,G_NODES=>G_NODES,G_MODE=>G_MODE,G_PERIOD_CYCLES=>G_PERIOD_CYCLES,G_ARM_DELAY_CYCLES=>G_ARM_DELAY_CYCLES,G_DRIFT_PPB=>node_drift(i),G_RUN_CYCLES=>G_RUN_CYCLES,G_RUNTIME_CONFIG=>G_RUNTIME_CONFIG)
  port map(clk_i=>clk_i,rst_i=>node_reset(i),start_i=>start_i,stop_i=>stop_i,links_up_i=>links_up_i,data_idle_i=>idle(i),
  left_rx_data_i=>lr_data(i),left_rx_keep_i=>lr_keep(i),left_rx_valid_i=>lr_valid(i),left_rx_last_i=>lr_last(i),
  right_rx_data_i=>rr_data(i),right_rx_keep_i=>rr_keep(i),right_rx_valid_i=>rr_valid(i),right_rx_last_i=>rr_last(i),
  left_tx_data_o=>engine_lt_data(i),left_tx_keep_o=>engine_lt_keep(i),left_tx_valid_o=>engine_lt_valid(i),left_tx_last_o=>engine_lt_last(i),left_tx_ready_i=>lt_ready(i),
  right_tx_data_o=>srt_data(i),right_tx_keep_o=>srt_keep(i),right_tx_valid_o=>srt_valid(i),right_tx_last_o=>srt_last(i),right_tx_ready_i=>srt_ready(i),
  launch_o=>launch(i),cycle_id_o=>cycles(i),running_o=>raw_running(i),sync_locked_o=>raw_locked(i),management_o=>mgmt(i),
  raw_counter_o=>raws(i),logical_time_o=>logical_times(i),offset_o=>offsets(i),path_delay_o=>delays(i),sync_window_miss_o=>misses(i),error_o=>raw_syncerr(i),config_mode_i=>cfg_mode,config_nodes_i=>cfg_nodes,config_id_i=>node_ids(i));
  engine_rt_data(i)<=srt_data(i) when mgmt(i)='1' else dt_data(i);
  engine_rt_keep(i)<=srt_keep(i) when mgmt(i)='1' else dt_keep(i);
  engine_rt_valid(i)<=srt_valid(i) when mgmt(i)='1' else dt_valid(i);
  engine_rt_last(i)<=srt_last(i) when mgmt(i)='1' else dt_last(i);
  srt_ready(i)<=rt_ready(i) and mgmt(i);dt_ready(i)<=rt_ready(i) and not mgmt(i);
  data_filter:entity work.data_frame_filter generic map(G_FIFO_WORDS=>G_FIFO_WORDS)
  port map(clk_i,node_reset(i),lr_data(i),lr_keep(i),lr_valid(i),lr_last(i),filtered_data(i),filtered_keep(i),filtered_valid(i),filtered_last(i),dr_ready(i),filter_empty(i),filter_overflow(i),filter_hw(i));
  rag:if G_MODE=0 or G_MODE=2 generate
  engine:entity work.rag_node generic map(G_MODE,G_NODES,G_NODE_BASE+i,G_DATA_BYTES,G_REF_BYTES,G_FIFO_WORDS,G_MAX_FRAME_BYTES,G_RUNTIME_CONFIG=>G_RUNTIME_CONFIG)
  port map(clk_i,node_reset(i),engine_start(i),cycles(i),filtered_data(i),filtered_keep(i),filtered_valid(i),filtered_last(i),dr_ready(i),
    dt_data(i),dt_keep(i),dt_valid(i),dt_last(i),dt_ready(i),raw_useful(i),raw_drained(i),raw_err(i),crcs(i),hw(i),ftx(i),frx(i),(others=>'0'),open,config_mode_i=>cfg_mode,config_nodes_i=>cfg_nodes,config_id_i=>node_ids(i),returned_o=>returned(i));
  end generate;
  agg:if G_MODE=1 or G_MODE=3 or G_MODE=4 generate
  engine:aggregate_node generic map(G_MODE,G_NODES,G_NODE_BASE+i,G_DATA_BYTES,G_REF_BYTES,G_FIFO_WORDS,G_MAX_FRAME_BYTES)
  port map(clk_i,node_reset(i),engine_start(i),cycles(i),filtered_data(i),filtered_keep(i),filtered_valid(i),filtered_last(i),dr_ready(i),
    dt_data(i),dt_keep(i),dt_valid(i),dt_last(i),dt_ready(i),raw_useful(i),raw_drained(i),raw_err(i),crcs(i),hw(i),ftx(i),frx(i),(others=>'0'),open);
  end generate;
  internal:if i<G_LOCAL_NODES-1 generate
   signal vf_data,vr_data:std_logic_vector(15 downto 0);
   signal vf_keep,vr_keep:std_logic_vector(1 downto 0);
   signal vf_valid,vf_last,vr_valid,vr_last,vf_ready,vr_ready,vf_empty,vr_empty:std_logic;
  begin
   vf:entity work.virtual_neighbor_link generic map(G_LATENCY_CYCLES=>G_VLINK_LATENCY,G_FIFO_WORDS=>G_VLINK_FIFO_WORDS,G_CC_PHASE=>(G_NODE_BASE+i)*71)
    port map(clk_i,node_rst,rt_data(i),rt_keep(i),rt_valid(i) and enabled(i+1),rt_last(i),vf_ready,vf_data,vf_keep,vf_valid,vf_last,vf_empty,open);
   rt_ready(i)<=vf_ready when enabled(i+1)='1' else rt_ready(i+1);
   lr_data(i+1)<=vf_data when enabled(i+1)='1' else rt_data(i);
   lr_keep(i+1)<=vf_keep when enabled(i+1)='1' else rt_keep(i);
   lr_valid(i+1)<=vf_valid when enabled(i+1)='1' else rt_valid(i);
   lr_last(i+1)<=vf_last when enabled(i+1)='1' else rt_last(i);
   forward_empty(i)<=vf_empty when enabled(i+1)='1' else '1';
   vr:entity work.virtual_neighbor_link generic map(G_LATENCY_CYCLES=>G_VLINK_LATENCY,G_FIFO_WORDS=>G_VLINK_FIFO_WORDS,G_CC_PHASE=>(G_NODE_BASE+i)*113+17)
    port map(clk_i,node_rst,lt_data(i+1),lt_keep(i+1),lt_valid(i+1) and enabled(i+1),lt_last(i+1),vr_ready,vr_data,vr_keep,vr_valid,vr_last,vr_empty,open);
   lt_ready(i+1)<=vr_ready when enabled(i+1)='1' else lt_ready(i);
   rr_data(i)<=vr_data when enabled(i+1)='1' else lt_data(i+1);
   rr_keep(i)<=vr_keep when enabled(i+1)='1' else lt_keep(i+1);
   rr_valid(i)<=vr_valid when enabled(i+1)='1' else lt_valid(i+1);
   rr_last(i)<=vr_last when enabled(i+1)='1' else lt_last(i+1);
   reverse_empty(i)<=vr_empty when enabled(i+1)='1' else '1';
  end generate;
 end generate;
 all_useful<=(and useful) and not transport_error and not link_error;all_locked<=and locked;
 all_drained<=(and drained) and (and forward_empty) and (and reverse_empty) and capempty_l and capempty_r and (and filter_empty);
 any_error<=(or err) or (or syncerr) or capoverflow_l or capoverflow_r or transport_error or link_error or (or filter_overflow);
 raw_counter_o<=std_logic_vector(raw);status_o<=summary(255 downto 39)&(not config_valid)&summary(37 downto 0);
 -- Registered read fits synchronous block RAM; host waits after changing address.
 process(clk_i) begin if rising_edge(clk_i) then log_read<=journal(to_integer(unsigned(log_addr_i)));end if;end process;
 log_data_o<=log_read;
 process(clk_i)
 variable crc_sum:unsigned(31 downto 0);variable maxhw:unsigned(15 downto 0);
 variable record_v:std_logic_vector(511 downto 0);variable flags:std_logic_vector(31 downto 0);
 begin if rising_edge(clk_i) then
 if rst_i='1' or config_valid='0' then seen_return<='0';treturn<=(others=>'1');engine_start<=(others=>'0');transport_error<='0';link_error<='0';previous_links<='0';channel_resets<=(others=>'0');raw<=(others=>'0');measuring<='0';recorded<='0';seen_useful<='0';seen_tx<='0';deadline_count<=(others=>'0');sequence_id<=(others=>'0');log_wr<=0;summary<=(others=>'0');
 else
 engine_start<=launch;previous_links<=links_up_i;
 if (previous_links='1' and links_up_i='0') or link_fault_i='1' then link_error<='1';channel_resets<=channel_resets+1;end if;
 for i in 0 to G_LOCAL_NODES-1 loop
 if filter_overflow(i)='1' then transport_error<='1';end if;end loop;
 raw<=raw+1;crc_sum:=(others=>'0');maxhw:=unsigned(caphw_l);if unsigned(caphw_r)>maxhw then maxhw:=unsigned(caphw_r);end if;
 for i in 0 to G_LOCAL_NODES-1 loop crc_sum:=crc_sum+unsigned(crcs(i));if unsigned(hw(i))>maxhw then maxhw:=unsigned(hw(i));end if;if unsigned(filter_hw(i))>maxhw then maxhw:=unsigned(filter_hw(i));end if;end loop;
 summary(31 downto 0)<=cycles(0);summary(32)<=and running;summary(33)<=all_locked;summary(34)<=all_useful;summary(35)<=all_drained;summary(36)<=any_error;summary(37)<=measuring;
 summary(63 downto 48)<=std_logic_vector(maxhw);summary(95 downto 64)<=std_logic_vector(crc_sum);summary(127 downto 96)<=std_logic_vector(deadline_count);
 summary(38)<=not config_valid;
 summary(159 downto 128)<=std_logic_vector(sequence_id);summary(191 downto 160)<=std_logic_vector(to_unsigned(cfg_mode,32));summary(223 downto 192)<=std_logic_vector(to_unsigned(cfg_nodes,32));summary(255 downto 224)<=std_logic_vector(to_unsigned(cfg_base,32));
 if launch(0)='1' then
  if measuring='1' and recorded='0' then deadline_count<=deadline_count+1;end if;
  seen_return<='0';treturn<=(others=>'1');t0<=raw;tuse<=(others=>'1');ttx<=(others=>'1');seen_useful<='0';seen_tx<='0';measuring<='1';recorded<='0';
 end if;
 if measuring='1' and launch(0)='0' and engine_start(0)='0' then
  if seen_return='0' and returned(0)='1' then treturn<=raw-t0;seen_return<='1';end if;
  if seen_useful='0' and all_useful='1' then tuse<=raw-t0;seen_useful<='1';end if;
  if seen_tx='0' and (or ftx)='1' then ttx<=raw-t0;seen_tx<='1';end if;
  if raw-t0=G_PERIOD_CYCLES then deadline_count<=deadline_count+1;end if;
  if recorded='0' and (all_drained='1' or raw-t0=G_PERIOD_CYCLES) then
   record_v:=(others=>'0');flags:=(others=>'0');flags(0):=any_error;flags(1):=capoverflow_l or capoverflow_r;
   if all_drained='0' then flags(2):='1';end if;flags(3):=or syncerr;flags(4):=all_locked;flags(6):=link_error;flags(7):=transport_error;
   if seen_useful='0' and all_useful='0' then flags(5):='1';end if;
   record_v(31 downto 0):=cycles(0);record_v(95 downto 32):=std_logic_vector(t0);
   record_v(159 downto 96):=std_logic_vector(tuse);if seen_useful='0' and all_useful='1' then record_v(159 downto 96):=std_logic_vector(raw-t0);end if;
   record_v(223 downto 160):=std_logic_vector(raw-t0);if all_drained='0' then record_v(223 downto 160):=(others=>'1');end if;
   record_v(287 downto 224):=std_logic_vector(ttx);
   if G_RUNTIME_CONFIG then
    flags(8):='1';record_v(287 downto 224):=std_logic_vector(treturn);
    if seen_return='0' and returned(0)='1' then record_v(287 downto 224):=std_logic_vector(raw-t0);end if;
   end if;record_v(319 downto 288):=std_logic_vector(crc_sum);
   record_v(351 downto 320):=flags;record_v(367 downto 352):=std_logic_vector(maxhw);
   record_v(383 downto 368):=std_logic_vector(to_unsigned(cfg_base,16));record_v(399 downto 384):=std_logic_vector(to_unsigned(cfg_local,16));
   record_v(415 downto 400):=std_logic_vector(to_unsigned(cfg_nodes,16));record_v(447 downto 416):=std_logic_vector(to_unsigned(cfg_mode,32));
   record_v(479 downto 448):=std_logic_vector(sequence_id+1);record_v(511 downto 480):=std_logic_vector(to_unsigned(G_PERIOD_CYCLES,32));
   journal(log_wr)<=record_v;sequence_id<=sequence_id+1;if log_wr=255 then log_wr<=0;else log_wr<=log_wr+1;end if;
   recorded<='1';if all_drained='1' then measuring<='0';end if;
  elsif recorded='1' and all_drained='1' then measuring<='0';end if;
 end if;
 end if;end if;end process;
end;

