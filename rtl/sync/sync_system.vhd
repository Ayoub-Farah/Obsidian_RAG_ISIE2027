library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.sync_math_pkg.all;

entity sync_system is
 generic(G_NODE_ID:natural:=0;G_NODES:positive:=3;G_MODE:natural:=2;G_PERIOD_CYCLES:positive:=6250;G_ARM_DELAY_CYCLES:positive:=312500;G_SYNC_INTERVAL:positive:=10;G_WINDOW_CYCLES:positive:=625;G_LOCK_SAMPLES:positive:=8;G_EXCHANGE_SPACING:positive:=256;G_DRIFT_PPB:integer:=0;G_RUN_CYCLES:natural:=128;G_RUNTIME_CONFIG:boolean:=false;G_EXTERNAL_SCHEDULER:boolean:=false);
 port(clk_i,rst_i,start_i,stop_i,links_up_i,data_idle_i:in std_logic;
 left_rx_data_i:in std_logic_vector(15 downto 0);left_rx_keep_i:in std_logic_vector(1 downto 0);left_rx_valid_i,left_rx_last_i:in std_logic;
 right_rx_data_i:in std_logic_vector(15 downto 0);right_rx_keep_i:in std_logic_vector(1 downto 0);right_rx_valid_i,right_rx_last_i:in std_logic;
 left_tx_data_o:out std_logic_vector(15 downto 0);left_tx_keep_o:out std_logic_vector(1 downto 0);left_tx_valid_o,left_tx_last_o:out std_logic;left_tx_ready_i:in std_logic;
 right_tx_data_o:out std_logic_vector(15 downto 0);right_tx_keep_o:out std_logic_vector(1 downto 0);right_tx_valid_o,right_tx_last_o:out std_logic;right_tx_ready_i:in std_logic;
 launch_o:out std_logic;cycle_id_o:out std_logic_vector(31 downto 0);running_o,sync_locked_o,management_o:out std_logic;
 raw_counter_o,logical_time_o,offset_o,path_delay_o:out std_logic_vector(63 downto 0);sync_window_miss_o:out std_logic_vector(31 downto 0);error_o:out std_logic;
 config_mode_i:in natural range 0 to 4:=G_MODE;
 config_nodes_i:in positive range 1 to G_NODES:=G_NODES;
 config_id_i:in natural range 0 to G_NODES-1:=G_NODE_ID;
 external_raw_i,left_rx_raw_i,right_rx_raw_i,left_rx_time_i,right_rx_time_i:in std_logic_vector(63 downto 0):=(others=>'0');
 busy_o:out std_logic:='0';holdover_o:out std_logic:='0';
 audit_left_o,audit_right_o:out std_logic_vector(255 downto 0):=(others=>'0'));
end;
architecture rtl of sync_system is
 constant C_Q:signed(63 downto 0):=to_signed(65536,64);
 -- Synthetic E2 oscillator; Q48.32 internal, Q48.16 on the wire.
 constant C_LOGICAL_STEP:signed(79 downto 0):=shift_left(to_signed(1,80),32)+shift_left(to_signed(G_DRIFT_PPB,80),32)/to_signed(1000000000,80);
 signal logical_accum:unsigned(79 downto 0):=(others=>'0');
 constant C_PERIOD:unsigned(63 downto 0):=shift_left(to_unsigned(G_PERIOD_CYCLES,64),16);
 signal history:hist_t:=(others=>(others=>'0'));signal hist_count:natural range 0 to 8:=0;signal hist_ptr:natural range 0 to 7:=0;
 signal raw:unsigned(63 downto 0):=(others=>'0');signal correction:signed(63 downto 0):=(others=>'0');signal logical:std_logic_vector(63 downto 0);
 signal pending_correction:signed(63 downto 0):=(others=>'0');signal correction_pending:std_logic:='0';signal path:signed(63 downto 0):=(others=>'0');
 signal active,locked,run,armed,arm_sent,ready_sent,child_ready,ready_pending,ack_pending,arm_pending,arm_returned:std_logic:='0';
 signal child_locked:std_logic:='0';signal stable:natural range 0 to G_LOCK_SAMPLES:=0;
 signal epoch,next_epoch:unsigned(63 downto 0):=(others=>'0');signal cycle:unsigned(31 downto 0):=(others=>'0');signal misses:unsigned(31 downto 0):=(others=>'0');signal sticky_error:std_logic:='0';
 signal window_open,window_requested,window_skip,round_started:std_logic:='0';signal round_id:natural range 0 to G_SYNC_INTERVAL-1:=0;
 signal parent_state:natural range 0 to 5:=0;signal child_state:natural range 0 to 2:=0;signal spacing:natural range 0 to G_EXCHANGE_SPACING:=0;
 signal pseq,cseq:std_logic_vector(31 downto 0):=(others=>'0');signal p_t1,p_t4,c_t1,c_t2,c_t3:std_logic_vector(63 downto 0):=(others=>'0');
 signal lr,rr,ldone,rdone,lready,rready,levent,revent,lerror,rerror:std_logic:='0';
 signal lkind,rkind,lk,rk:std_logic_vector(7 downto 0):=(others=>'0');signal ls,rs,lseq,rseq:std_logic_vector(31 downto 0):=(others=>'0');
 signal lt,rt,ltxstamp,rtxstamp,lstamp,rstamp,lts,rts:std_logic_vector(63 downto 0):=(others=>'0');
 signal hold_age:natural range 0 to 2*G_SYNC_INTERVAL*G_PERIOD_CYCLES:=0;
 signal timeout:natural range 0 to 65535:=0;signal stop_pending:std_logic:='0';
 signal previous_start,start_edge:std_logic:='0';
 signal mgmt:std_logic;
 signal nodes_cfg:positive range 1 to G_NODES:=G_NODES;
 signal id_cfg:natural range 0 to G_NODES-1:=G_NODE_ID;
 signal lbegin,rbegin:std_logic;
 signal ltxraw,rtxraw,lrxraw,rrxraw:std_logic_vector(63 downto 0);
 signal accepted_sample:std_logic:='0';
 signal history_median:signed(63 downto 0):=(others=>'0');

begin
 -- Accepted exchanges are separated by complete management frames. Register
 -- the median between exchanges, removing the rank/select network from the
 -- same-cycle outlier-decision path without moving any TX/RX timestamp.
 process(clk_i) begin if rising_edge(clk_i) then
   if rst_i='1' then history_median<=(others=>'0');else history_median<=median(history);end if;
 end if;end process;
 nodes_cfg<=config_nodes_i when G_RUNTIME_CONFIG else G_NODES;
 id_cfg<=config_id_i when G_RUNTIME_CONFIG else G_NODE_ID;
 assert G_NODE_ID<G_NODES severity failure;
 start_edge<=start_i and not previous_start;
 assert G_WINDOW_CYCLES<G_PERIOD_CYCLES severity failure;
 logical<=std_logic_vector(signed(logical_accum(79 downto 16))+correction);
 raw_counter_o<=std_logic_vector(raw);logical_time_o<=logical;offset_o<=std_logic_vector(correction);path_delay_o<=std_logic_vector(path);cycle_id_o<=std_logic_vector(cycle);running_o<=run;sync_locked_o<=locked;sync_window_miss_o<=std_logic_vector(misses);error_o<=sticky_error;
 mgmt<='1' when run='0' or window_open='1' else '0';management_o<=mgmt;
 busy_o<='1' when parent_state/=0 or child_state/=0 or lready='0' or rready='0' or lr='1' or rr='1' or window_open='1' else '0';
 holdover_o<='1' when hold_age=2*G_SYNC_INTERVAL*G_PERIOD_CYCLES else '0';
 lcodec:entity work.management_codec generic map(G_NODE_ID,G_NODES,G_MODE,G_PERIOD_CYCLES,G_RUNTIME_CONFIG=>G_RUNTIME_CONFIG,G_EXTERNAL_STAMPS=>G_EXTERNAL_SCHEDULER)
 port map(clk_i,rst_i,logical,lr,lk,ls,lt,lready,ldone,ltxstamp,left_tx_data_o,left_tx_keep_o,left_tx_valid_o,left_tx_last_o,left_tx_ready_i,left_rx_data_i,left_rx_keep_i,left_rx_valid_i,left_rx_last_i,levent,lkind,lseq,lts,lstamp,lerror,config_mode_i,config_nodes_i,config_id_i,external_raw_i,left_rx_raw_i,left_rx_time_i,lbegin,ltxraw,lrxraw);
 rcodec:entity work.management_codec generic map(G_NODE_ID,G_NODES,G_MODE,G_PERIOD_CYCLES,false,G_RUNTIME_CONFIG,G_EXTERNAL_SCHEDULER)
 port map(clk_i,rst_i,logical,rr,rk,rs,rt,rready,rdone,rtxstamp,right_tx_data_o,right_tx_keep_o,right_tx_valid_o,right_tx_last_o,right_tx_ready_i,right_rx_data_i,right_rx_keep_i,right_rx_valid_i,right_rx_last_i,revent,rkind,rseq,rts,rstamp,rerror,config_mode_i,config_nodes_i,config_id_i,external_raw_i,right_rx_raw_i,right_rx_time_i,rbegin,rtxraw,rrxraw);
 -- Export actual raw/logical PTP events. Bit254 signals a same-port collision.
 process(clk_i)
 variable a,b:std_logic_vector(255 downto 0);
 begin if rising_edge(clk_i) then
 a:=(others=>'0');b:=(others=>'0');
 if lbegin='1' then a(255):='1';a(170):='1';a(63 downto 0):=ltxraw;a(127 downto 64):=ltxstamp;a(159 downto 128):=ls;a(167 downto 160):=lk;end if;
 if levent='1' then a(255):='1';a(170):='0';a(254):=lbegin;a(63 downto 0):=lrxraw;a(127 downto 64):=lstamp;a(159 downto 128):=lseq;a(167 downto 160):=lkind;end if;
 if accepted_sample='1' then a(254):=a(255);a(255):='1';a(170):='0';a(63 downto 0):=external_raw_i;a(127 downto 64):=logical;a(159 downto 128):=cseq;a(167 downto 160):=x"15";end if;
 if id_cfg>0 then a(169 downto 168):=std_logic_vector(to_unsigned(id_cfg-1,2));end if;
 if rbegin='1' then b(255):='1';b(170):='1';b(63 downto 0):=rtxraw;b(127 downto 64):=rtxstamp;b(159 downto 128):=rs;b(167 downto 160):=rk;end if;
 if revent='1' then b(255):='1';b(170):='0';b(254):=rbegin;b(63 downto 0):=rrxraw;b(127 downto 64):=rstamp;b(159 downto 128):=rseq;b(167 downto 160):=rkind;end if;
 if id_cfg<2 then b(169 downto 168):=std_logic_vector(to_unsigned(id_cfg+1,2));end if;
 a(171):='0';b(171):='1';audit_left_o<=a;audit_right_o<=b;
 end if;end process;
 process(clk_i)
 variable theta,delay_est,delta:signed(63 downto 0);variable good:boolean;
 begin if rising_edge(clk_i) then
 previous_start<=start_i;raw<=raw+1;logical_accum<=logical_accum+unsigned(C_LOGICAL_STEP);launch_o<='0';lr<='0';rr<='0';accepted_sample<='0';
 if rst_i='1' then
 previous_start<='0';stop_pending<='0';raw<=(others=>'0');logical_accum<=(others=>'0');correction<=(others=>'0');correction_pending<='0';active<='0';locked<='0';run<='0';armed<='0';arm_sent<='0';ready_sent<='0';child_ready<='0';ready_pending<='0';ack_pending<='0';arm_pending<='0';arm_returned<='0';child_locked<='0';stable<=0;parent_state<=0;child_state<=0;spacing<=0;hist_count<=0;hist_ptr<=0;epoch<=(others=>'0');next_epoch<=(others=>'0');cycle<=(others=>'0');misses<=(others=>'0');sticky_error<='0';window_open<='0';window_requested<='0';window_skip<='0';round_started<='0';round_id<=0;pseq<=(others=>'0');timeout<=0;hold_age<=0;
 else
 if lerror='1' or rerror='1' then sticky_error<='1';end if;
 if run='0' then hold_age<=0;elsif id_cfg>0 then
 if hold_age<2*G_SYNC_INTERVAL*G_PERIOD_CYCLES then hold_age<=hold_age+1;
 elsif not G_EXTERNAL_SCHEDULER then sticky_error<='1';locked<='0';stop_pending<='1';end if;end if;
 if stop_i='1' then stop_pending<='1';elsif start_edge='1' and run='0' then stop_pending<='0';end if;
 if links_up_i='0' then
 active<='0';locked<='0';run<='0';armed<='0';parent_state<=0;child_state<=0;window_open<='0';child_locked<='0';ready_sent<='0';arm_sent<='0';child_ready<='0';arm_returned<='0';stable<=0;correction_pending<='0';
 else
 if (stop_pending='1' or stop_i='1') and data_idle_i='1' and parent_state=0 and child_state=0 and lready='1' and rready='1' and lr='0' and rr='0' then
 active<='0';locked<='0';run<='0';armed<='0';window_open<='0';ready_sent<='0';arm_sent<='0';child_ready<='0';arm_returned<='0';ready_pending<='0';ack_pending<='0';arm_pending<='0';stop_pending<='0';stable<=0;child_locked<='0';correction_pending<='0';
 else
 if id_cfg=0 and start_edge='1' and active='0' then active<='1';locked<='1';stop_pending<='0';end if;
 -- First frame from the parent activates a follower without a local JTAG start.
 if id_cfg>0 and levent='1' and lkind=x"10" then
 active<='1';cseq<=lseq;c_t2<=lstamp;child_state<=1;timeout<=0;
 end if;
 if active='1' and spacing<G_EXCHANGE_SPACING then spacing<=spacing+1;end if;
 if child_state/=0 or parent_state/=0 then
 if timeout<65535 then timeout<=timeout+1;else sticky_error<='1';locked<='0';run<='0';armed<='0';parent_state<=0;child_state<=0;active<='0';end if;
 else timeout<=0;end if;
 -- Parent role; a locked node starts the next pair in the initial cascade.
 if active='1' and locked='1' and id_cfg<nodes_cfg-1 and parent_state=0 and arm_pending='0' and ready_sent='0' and child_ready='0' and rready='1' and rr='0' and stop_pending='0' and stop_i='0' then
 if (run='0' and armed='0' and spacing=G_EXCHANGE_SPACING) or (run='1' and window_open='1' and round_started='0') then
 pseq<=std_logic_vector(unsigned(pseq)+1);rs<=std_logic_vector(unsigned(pseq)+1);rk<=x"10";rt<=(others=>'0');rr<='1';parent_state<=1;spacing<=0;round_started<='1';
 end if;end if;
 if parent_state=1 and rdone='1' then p_t1<=rtxstamp;parent_state<=2;end if;
 if parent_state=2 and rready='1' and rr='0' then rk<=x"11";rs<=pseq;rt<=p_t1;rr<='1';parent_state<=3;end if;
 if parent_state=3 and rdone='1' then parent_state<=4;end if;
 if revent='1' and rkind=x"12" and rseq=pseq and parent_state=4 then p_t4<=rstamp;parent_state<=5;end if;
 if parent_state=5 and rready='1' and rr='0' then rk<=x"13";rs<=pseq;rt<=p_t4;rr<='1';parent_state<=0;end if;
 if revent='1' and rkind=x"14" then child_locked<='1';end if;
 -- Child role. FOLLOW_UP carries the actual accepted first-word TX stamp.
 if id_cfg>0 and child_state=1 and levent='1' and lkind=x"11" and lseq=cseq and lready='1' and lr='0' then
 c_t1<=lts;lk<=x"12";ls<=cseq;lt<=(others=>'0');lr<='1';child_state<=2;
 end if;
 if child_state=2 and ldone='1' then c_t3<=ltxstamp;end if;
 if id_cfg>0 and child_state=2 and levent='1' and lkind=x"13" and lseq=cseq then
 theta:=shift_right((signed(c_t2)-signed(c_t1))-(signed(lts)-signed(c_t3)),1);
 delay_est:=shift_right((signed(c_t2)-signed(c_t1))+(signed(lts)-signed(c_t3)),1);
 good:=delay_est>=0;
 if hist_count=8 and abs(delay_est-history_median)>4*C_Q then good:=false;end if;
 if run='1' and abs(theta)>4*C_Q and not G_EXTERNAL_SCHEDULER then good:=false;locked<='0';stop_pending<='1';sticky_error<='1';end if;
 if good then
 accepted_sample<='1';
 hold_age<=0;
 history(hist_ptr)<=delay_est;if hist_ptr=7 then hist_ptr<=0;else hist_ptr<=hist_ptr+1;end if;if hist_count<8 then hist_count<=hist_count+1;end if;
 path<=delay_est;pending_correction<=-theta;correction_pending<='1';
 if abs(theta)<=2*C_Q then
 if stable<G_LOCK_SAMPLES then stable<=stable+1;end if;
 if stable>=G_LOCK_SAMPLES-1 then locked<='1';ack_pending<='1';end if;
 else stable<=0;if G_EXTERNAL_SCHEDULER then locked<='0';end if;end if;
 else stable<=0;end if;child_state<=0;
 end if;
 -- Mapping is held throughout BOTH concurrent parent/child transactions.
 if correction_pending='1' and child_state=0 and parent_state=0 and lready='1' and rready='1' and lr='0' and rr='0' and data_idle_i='1' then
 correction<=correction+pending_correction;correction_pending<='0';
 end if;
 -- READY rises up the chain only after the local child is completely ready.
 if revent='1' and rkind=x"21" then
 if unsigned(rts(63 downto 48))=to_unsigned(nodes_cfg-id_cfg-1,16) and unsigned(rts(47 downto 0))=0 then child_ready<='1';else sticky_error<='1';end if;
 end if;
 if stop_pending='0' and stop_i='0' and locked='1' and (id_cfg=nodes_cfg-1 or child_ready='1') and ready_sent='0' and armed='0' then
 if id_cfg=0 then
 epoch<=unsigned(logical)+shift_left(to_unsigned(G_ARM_DELAY_CYCLES,64),16);arm_pending<='1';ready_sent<='1';
 else ready_pending<='1';end if;end if;
 if id_cfg>0 and lready='1' and lr='0' and child_state=0 then
 if ack_pending='1' then lk<=x"14";ls<=cseq;lt<=(others=>'0');lr<='1';ack_pending<='0';
 elsif ready_pending='1' then lk<=x"21";ls<=(others=>'0');lt<=(others=>'0');lr<='1';ready_pending<='0';ready_sent<='1';end if;end if;
 -- ARM circulates forward and is removed by the anchor. Epoch is common Q48.16.
 if levent='1' and lkind=x"20" then
 if id_cfg=0 then arm_returned<='1';
 elsif locked='1' then epoch<=unsigned(lts);armed<='1';arm_pending<='1';end if;
 end if;
 if arm_pending='1' and rready='1' and rr='0' and parent_state=0 then rk<=x"20";rs<=(others=>'0');rt<=std_logic_vector(epoch);rr<='1';arm_pending<='0';arm_sent<='1';end if;
 if id_cfg=0 and arm_returned='1' and armed='0' then armed<='1';end if;
 -- No launch is emitted until every node has accepted ARM and it returned to0.
 if stop_pending='0' and stop_i='0' and armed='1' and run='0' and unsigned(logical)>=epoch then
 if unsigned(logical)-epoch<C_PERIOD and (id_cfg/=0 or arm_returned='1') then
 run<='1';launch_o<='1';cycle<=(others=>'0');next_epoch<=epoch+C_PERIOD;round_id<=0;window_open<='0';window_requested<='0';window_skip<='0';round_started<='0';
 else sticky_error<='1';armed<='0';active<='0';end if;
 elsif run='1' and G_EXTERNAL_SCHEDULER then
 -- The physical coordinator owns trial epochs. Maintenance is permitted only
 -- after its global retirement/drain barrier, never by a local idle guess.
 if unsigned(logical)>=next_epoch then
   next_epoch<=unsigned(logical)+C_PERIOD;
   if round_id=G_SYNC_INTERVAL-1 then round_id<=0;window_requested<='1';
     if data_idle_i='1' then window_open<='1';round_started<='0';else misses<=misses+1;end if;
   else round_id<=round_id+1;end if;
 end if;
 if window_open='1' and round_started='1' and parent_state=0 and child_state=0 and lready='1' and rready='1' and lr='0' and rr='0' then window_open<='0';end if;
 if id_cfg=nodes_cfg-1 and window_open='1' and child_state=0 then window_open<='0';end if;
 elsif run='1' then
 if unsigned(logical)>=next_epoch and stop_pending='0' and stop_i='0' then
 -- A correction can never silently cause multiple catch-up launches.
 if G_RUN_CYCLES>0 and cycle+1>=to_unsigned(G_RUN_CYCLES,32) then
 stop_pending<='1';if data_idle_i='0' then sticky_error<='1';end if;
 elsif unsigned(logical)-next_epoch>=C_PERIOD or data_idle_i='0' or parent_state/=0 or child_state/=0 or lready='0' or rready='0' then
 sticky_error<='1';stop_pending<='1';
 else launch_o<='1';cycle<=cycle+1;next_epoch<=next_epoch+C_PERIOD;window_open<='0';window_requested<='0';window_skip<='0';round_started<='0';
 if round_id=G_SYNC_INTERVAL-1 then round_id<=0;else round_id<=round_id+1;end if;end if;
 elsif round_id=G_SYNC_INTERVAL-1 and unsigned(logical)>=next_epoch-shift_left(to_unsigned(G_WINDOW_CYCLES,64),16) and window_requested='0' then
 window_requested<='1';if data_idle_i='1' then window_open<='1';else misses<=misses+1;window_skip<='1';end if;
 end if;
 end if;
 -- During run, release suffix-readiness gates so all parents maintain in parallel.
 if run='1' then ready_sent<='0';child_ready<='0';end if;
 end if;end if;end if;end if;
 end process;
end;
