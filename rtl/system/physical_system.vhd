library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.benchmark_pkg.all;
use work.physical_pkg.all;
entity physical_system is
  generic(G_SYNC_ARM_DELAY:positive:=312500;G_SYNC_DRIFT_PPB:integer:=0;G_ARM_GUARD:positive:=1024);
  port(clk_i,rst_i:in std_logic;links_up_i,link_fault_i:in std_logic;
    configure_i,start_i,stop_i,page_ack_i:in std_logic;
    config_i:in config_t;role_i:in unsigned(1 downto 0);
    left_rx_data_i,right_rx_data_i:in std_logic_vector(15 downto 0);
    left_rx_keep_i,right_rx_keep_i:in std_logic_vector(1 downto 0);
    left_rx_valid_i,left_rx_last_i,right_rx_valid_i,right_rx_last_i:in std_logic;
    left_tx_data_o,right_tx_data_o:out std_logic_vector(15 downto 0);
    left_tx_keep_o,right_tx_keep_o:out std_logic_vector(1 downto 0);
    left_tx_valid_o,left_tx_last_o,right_tx_valid_o,right_tx_last_o:out std_logic;
    left_tx_ready_i,right_tx_ready_i:in std_logic;
    status_o:out std_logic_vector(255 downto 0);raw_o,logical_o:out std_logic_vector(63 downto 0);
    active_o:out config_t;log_addr_i:in unsigned(12 downto 0);log_data_o:out std_logic_vector(63 downto 0);
    lost_o:out std_logic_vector(63 downto 0));
end;
architecture rtl of physical_system is
  signal raw:ticks_t:=(others=>'0');signal logical,offset,path_delay:std_logic_vector(63 downto 0);
  signal active_cfg:config_t;signal board:unsigned(1 downto 0);signal sync_id:natural range 0 to 2:=0;
  signal configured,maintenance,sync_start,sync_running,sync_locked,sync_busy,sync_holdover,sync_reset:std_logic;
  signal ld,rd:std_logic_vector(15 downto 0);signal lk,rk:std_logic_vector(1 downto 0);
  signal ldata,lsync,lcontrol,llast,rdata,rsync,rcontrol,rlast,lbusy,rbusy,lerror,rerror:std_logic;
  signal lstamp,rstamp:ticks_t;
  signal ltime,rtime:std_logic_vector(63 downto 0);
  signal sld,srd,nd,cd:std_logic_vector(15 downto 0);signal slk,srk,nk,ck:std_logic_vector(1 downto 0);
  signal slv,sync_llast,srv,sync_rlast,srr,nv,nl,nready,cv,cl,cready:std_logic;
  signal launch,node_idle,node_fault,removed,removed_bad:std_logic;
  signal removed_origin:unsigned(1 downto 0);signal removed_hops:unsigned(15 downto 0);
  signal run_id,trial_id:std_logic_vector(31 downto 0);
  signal tx_event,rx_event:event_t;signal tx_ev,rx_ev:std_logic;
  signal node_summary,summary:summary_t;
  signal append_summary,freeze,frozen,journal_busy:std_logic;signal count:unsigned(7 downto 0);
  signal skipped,epoch:ticks_t;signal lost_events,lost_cal:unsigned(31 downto 0);
  signal request,control_ready,control_event,control_error:std_logic;
  signal send_kind,recv_kind:byte_t;signal send_seq,recv_seq:std_logic_vector(31 downto 0);
  signal send_time,recv_time:std_logic_vector(63 downto 0);signal send_payload,recv_payload:control_payload_t;
  signal forward_owner,selected:natural range 0 to 3:=0;
  signal out_valid,out_last:std_logic;
  signal audit_l,audit_r:std_logic_vector(255 downto 0);
  signal status:std_logic_vector(255 downto 0);signal trial_holdover:std_logic:='0';
  signal tx_request_pending:std_logic;
begin
  process(clk_i) begin if rising_edge(clk_i) then
    if rst_i='1' then raw<=(others=>'0');else raw<=raw+1;end if;
    if rst_i='1' or launch='1' then trial_holdover<='0';
    elsif status(11)='1' and sync_holdover='1' then trial_holdover<='1';end if;
  end if;end process;
  raw_o<=std_logic_vector(raw);logical_o<=logical;active_o<=active_cfg;status_o<=status;
  lost_o<=std_logic_vector(lost_cal)&std_logic_vector(lost_events);
  left_router:entity work.physical_rx_router port map(clk_i,rst_i,raw,left_rx_data_i,left_rx_keep_i,left_rx_valid_i,left_rx_last_i,
    ld,lk,ldata,lsync,lcontrol,llast,lstamp,lbusy,lerror);
  right_router:entity work.physical_rx_router port map(clk_i,rst_i,raw,right_rx_data_i,right_rx_keep_i,right_rx_valid_i,right_rx_last_i,
    rd,rk,rdata,rsync,rcontrol,rlast,rstamp,rbusy,rerror);
  ltime<=std_logic_vector(unsigned(logical)-shift_left(raw-lstamp,16));
  rtime<=std_logic_vector(unsigned(logical)-shift_left(raw-rstamp,16));
  sync_id<=to_integer(board) when board/="11" else 0;
  sync_reset<=rst_i or not configured;
  sync:entity work.sync_system
    generic map(G_NODES=>3,G_MODE=>2,G_ARM_DELAY_CYCLES=>G_SYNC_ARM_DELAY,G_DRIFT_PPB=>G_SYNC_DRIFT_PPB,
      G_RUN_CYCLES=>0,G_RUNTIME_CONFIG=>true,G_EXTERNAL_SCHEDULER=>true)
    port map(clk_i=>clk_i,rst_i=>sync_reset,start_i=>sync_start,stop_i=>'0',links_up_i=>links_up_i,data_idle_i=>maintenance,
      left_rx_data_i=>ld,left_rx_keep_i=>lk,left_rx_valid_i=>lsync,left_rx_last_i=>llast,
      right_rx_data_i=>rd,right_rx_keep_i=>rk,right_rx_valid_i=>rsync,right_rx_last_i=>rlast,
      left_tx_data_o=>sld,left_tx_keep_o=>slk,left_tx_valid_o=>slv,left_tx_last_o=>sync_llast,left_tx_ready_i=>left_tx_ready_i,
      right_tx_data_o=>srd,right_tx_keep_o=>srk,right_tx_valid_o=>srv,right_tx_last_o=>sync_rlast,right_tx_ready_i=>srr,
      launch_o=>open,cycle_id_o=>open,running_o=>sync_running,sync_locked_o=>sync_locked,management_o=>open,
      raw_counter_o=>open,logical_time_o=>logical,offset_o=>offset,path_delay_o=>path_delay,sync_window_miss_o=>open,error_o=>open,
      config_mode_i=>2,config_nodes_i=>3,config_id_i=>sync_id,
      external_raw_i=>std_logic_vector(raw),left_rx_raw_i=>std_logic_vector(lstamp),right_rx_raw_i=>std_logic_vector(rstamp),
      left_rx_time_i=>ltime,right_rx_time_i=>rtime,busy_o=>sync_busy,holdover_o=>sync_holdover,audit_left_o=>audit_l,audit_right_o=>audit_r);
  left_tx_data_o<=sld;left_tx_keep_o<=slk;left_tx_valid_o<=slv;left_tx_last_o<=sync_llast;
  node:entity work.physical_node port map(clk_i,rst_i,raw,active_cfg,board,launch,run_id,trial_id,
    ld,lk,ldata,llast,lstamp,nd,nk,nv,nl,nready,node_idle,node_fault,removed,removed_origin,removed_hops,removed_bad,
    tx_event,rx_event,tx_ev,rx_ev,node_summary);
  codec:entity work.ring_control_codec port map(clk_i,rst_i,raw,board,request,send_kind,send_seq,send_time,send_payload,control_ready,
    cd,ck,cv,cl,cready,ld,lk,lcontrol,llast,lstamp,control_event,control_error,recv_kind,open,recv_seq,recv_time,recv_payload,open);
  controller:entity work.physical_controller generic map(G_ARM_GUARD=>G_ARM_GUARD)
    port map(clk_i,rst_i,raw,logical,links_up_i,link_fault_i or lerror or rerror,
      config_i,role_i,configure_i,start_i,stop_i,page_ack_i,active_cfg,board,configured,
      sync_running,sync_locked,sync_busy,sync_holdover,sync_start,maintenance,
      node_idle,node_fault,removed,removed_origin,removed_hops,removed_bad,launch,run_id,trial_id,
      frozen,journal_busy,count,append_summary,freeze,skipped,epoch,
      control_event,control_error,recv_kind,recv_seq,recv_time,recv_payload,
      control_ready,request,send_kind,send_seq,send_time,send_payload,status);
  process(all)
    variable s:summary_t;
  begin
    s:=node_summary;s(228):=status(22);s(1183 downto 1120):=std_logic_vector(epoch);s(1247 downto 1184):=std_logic_vector(skipped);
    s(1248):=trial_holdover;s(1249):=sync_locked;s(1250):=sync_holdover;
    s(1343 downto 1280):=offset;s(1407 downto 1344):=path_delay;
    s(1471 downto 1408):=std_logic_vector(raw);s(1535 downto 1472):=logical;
    s(1567 downto 1536):=std_logic_vector(lost_events);s(1599 downto 1568):=std_logic_vector(lost_cal);
    s(1727 downto 1664):=(others=>'1');
    if board="00" and cfg_mode(active_cfg)=C_CT and unsigned(node_summary(399 downto 336))/=x"FFFFFFFFFFFFFFFF" and
      unsigned(node_summary(591 downto 528))/=x"FFFFFFFFFFFFFFFF" then
      s(1727 downto 1664):=std_logic_vector(unsigned(node_summary(591 downto 528))-unsigned(node_summary(399 downto 336)));
    end if;
    summary<=s;
  end process;
  journal:entity work.physical_journal port map(clk_i,rst_i,raw,board,active_cfg,
    summary,append_summary,freeze,page_ack_i,tx_event,rx_event,tx_ev,rx_ev,audit_l,audit_r,skipped,
    log_addr_i,log_data_o,frozen,journal_busy,count,lost_events,lost_cal);
  -- Frame ownership is held even when VALID drops while waiting for a tail.
  process(all) begin
    selected<=forward_owner;
    if forward_owner=0 then
      if srv='1' then selected<=3;elsif cv='1' then selected<=2;elsif nv='1' then selected<=1;end if;
    end if;
  end process;
  process(all) begin
    right_tx_data_o<=(others=>'0');right_tx_keep_o<="11";out_valid<='0';out_last<='0';
    srr<='0';cready<='0';nready<='0';
    case selected is
      when 1 => right_tx_data_o<=nd;right_tx_keep_o<=nk;out_valid<=nv;out_last<=nl;nready<=right_tx_ready_i;
      when 2 => right_tx_data_o<=cd;right_tx_keep_o<=ck;out_valid<=cv;out_last<=cl;cready<=right_tx_ready_i;
      when 3 => right_tx_data_o<=srd;right_tx_keep_o<=srk;out_valid<=srv;out_last<=sync_rlast;srr<=right_tx_ready_i;
      when others => null;
    end case;
  end process;
  right_tx_valid_o<=out_valid;right_tx_last_o<=out_last;
  process(clk_i) begin if rising_edge(clk_i) then
    if rst_i='1' then forward_owner<=0;
    elsif out_valid='1' and out_last='1' and right_tx_ready_i='1' then forward_owner<=0;
    elsif selected/=0 then forward_owner<=selected;end if;
  end if;end process;
end;
