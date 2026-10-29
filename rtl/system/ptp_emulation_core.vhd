-- One physical board, K complete PTP engines. No CT/RAG DATA path exists here.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.ptp_emulation_pkg.all;
entity ptp_emulation_core is
  generic(G_CAPACITY:positive:=1;G_MAX_NODES:positive:=3;G_ARM_DELAY:positive:=312500);
  port(clk_i,rst_i,state_reset_i,start_i,stop_i,links_up_i:in std_logic;
    nodes_i:in positive range 3 to G_MAX_NODES;board_i:in natural range 0 to 2;
    steps_i:in steps_t(0 to G_CAPACITY-1);offsets_i:in offsets_t(0 to G_CAPACITY-1);
    forward_i,reverse_i:in delays_t(0 to G_CAPACITY-1);
    jitter_i:in unsigned(7 downto 0);seed_i:in unsigned(31 downto 0);drop_every_i:in unsigned(15 downto 0);
    period_i:in positive range 626 to 16777215;interval_i:in positive range 1 to 65535;
    epoch_i:in unsigned(63 downto 0);width_i:in positive range 1 to 625;
    left_rx_data_i,right_rx_data_i:in std_logic_vector(15 downto 0);
    left_rx_keep_i,right_rx_keep_i:in std_logic_vector(1 downto 0);
    left_rx_valid_i,left_rx_last_i,right_rx_valid_i,right_rx_last_i:in std_logic;
    left_tx_data_o,right_tx_data_o:out std_logic_vector(15 downto 0);
    left_tx_keep_o,right_tx_keep_o:out std_logic_vector(1 downto 0);
    left_tx_valid_o,left_tx_last_o,right_tx_valid_o,right_tx_last_o:out std_logic;
    left_tx_ready_i,right_tx_ready_i:in std_logic;
    raw_o:out std_logic_vector(63 downto 0);
    times_o,corrections_o,delays_o,theta_o,ages_o:out words64_t(0 to G_CAPACITY-1);
    accepted_o,rejected_o,deferred_o,skipped_o,backsteps_o:out words32_t(0 to G_CAPACITY-1);
    marker_indices_o:out words64_t(0 to G_CAPACITY-1);
    running_o,locked_o,holdover_o,errors_o,pulses_o:out std_logic_vector(0 to G_CAPACITY-1);
    audits_left_o,audits_right_o:out audits_t(0 to G_CAPACITY-1);
    idle_o,overflow_o:out std_logic;
    dropped_o:out words32_t(0 to G_CAPACITY-1):=(others=>(others=>'0')));
end;
architecture rtl of ptp_emulation_core is
  signal raw:unsigned(63 downto 0):=(others=>'0');
  signal count:positive range 1 to G_CAPACITY:=1;signal first:natural range 0 to G_MAX_NODES-1:=0;
  signal ld,rd,lrx,rrx:words16_t(0 to G_CAPACITY-1);
  signal lk,rk,lrk,rrk:keeps_t(0 to G_CAPACITY-1);
  signal lv,rv,ll,rl,lready,rready,lrv,rrv,lrl,rrl,reset,enabled,idle,busy:std_logic_vector(0 to G_CAPACITY-1);
  signal link_idle_f,link_idle_r:std_logic_vector(0 to G_CAPACITY-1):=(others=>'1');
  signal times:words64_t(0 to G_CAPACITY-1);
  signal fd,bd:words16_t(0 to G_CAPACITY-1);signal fk,bk:keeps_t(0 to G_CAPACITY-1);
  signal fv,bv,fl,bl,fr,br:std_logic_vector(0 to G_CAPACITY-1):=(others=>'0');
  signal ext_ld,ext_rd:std_logic_vector(15 downto 0);signal ext_lk,ext_rk:std_logic_vector(1 downto 0);
  signal ext_lv,ext_rv,ext_ll,ext_rl,ext_lready,ext_rready,ext_li,ext_ri,link_reset:std_logic;
  signal overflow:std_logic:='0';
  signal ext_lraw,ext_rraw:std_logic_vector(63 downto 0);
  signal ext_ldrop,ext_rdrop:unsigned(31 downto 0);
  signal fdrop,bdrop:words32_t(0 to G_CAPACITY-1):=(others=>(others=>'0'));
begin
  assert G_MAX_NODES<=3*G_CAPACITY and G_MAX_NODES<=65535 severity failure;
  count<=population(nodes_i,board_i);first<=first_node(nodes_i,board_i);
  raw_o<=std_logic_vector(raw);times_o<=times;overflow_o<=overflow;
  link_reset<=rst_i or state_reset_i;
  process(clk_i) begin if rising_edge(clk_i) then
    if rst_i='1' then raw<=(others=>'0');else raw<=raw+1;end if;
    if link_reset='1' then overflow<='0';
    elsif (left_rx_valid_i='1' and ext_lready='0') or (right_rx_valid_i='1' and ext_rready='0') then overflow<='1';end if;
  end if;end process;
  -- Boundary injection is AFTER Aurora RX and BEFORE the receiving codec.
  -- Capture the local logical time at the delayed first word: injected delay
  -- must affect t2/t4. Aurora TX stamps remain actual accepted first-word times.
  ext_left:entity work.ptp_neighbor_link generic map(G_WORDS=>128)
    port map(clk_i,link_reset,forward_i(0),jitter_i,seed_i,drop_every_i,
      left_rx_data_i,left_rx_keep_i,left_rx_valid_i,left_rx_last_i,ext_lready,
      ext_ld,ext_lk,ext_lv,ext_ll,ext_li,ext_ldrop,std_logic_vector(raw),ext_lraw);
  ext_right:entity work.ptp_neighbor_link generic map(G_WORDS=>128)
    port map(clk_i,link_reset,reverse_i(count-1),jitter_i,seed_i xor x"9E3779B9",drop_every_i,
      right_rx_data_i,right_rx_keep_i,right_rx_valid_i,right_rx_last_i,ext_rready,
      ext_rd,ext_rk,ext_rv,ext_rl,ext_ri,ext_rdrop,std_logic_vector(raw),ext_rraw);
  left_tx_data_o<=ld(0);left_tx_keep_o<=lk(0);left_tx_valid_o<=lv(0);left_tx_last_o<=ll(0);
  right_tx_data_o<=rd(count-1);right_tx_keep_o<=rk(count-1);right_tx_valid_o<=rv(count-1);right_tx_last_o<=rl(count-1);
  lrx(0)<=ext_ld;lrk(0)<=ext_lk;lrv(0)<=ext_lv;lrl(0)<=ext_ll;lready(0)<=left_tx_ready_i;
  engines:for i in 0 to G_CAPACITY-1 generate
    signal id:natural range 0 to G_MAX_NODES-1;
    signal marker_idx:unsigned(63 downto 0);signal skipped,backsteps:unsigned(31 downto 0);
    signal rx_lraw,rx_rraw:std_logic_vector(63 downto 0);signal dl,dr:unsigned(31 downto 0);
  begin
    enabled(i)<='1' when i<count else '0';reset(i)<=link_reset or not enabled(i);
    id<=first+i when i<count else 0;
    rx_lraw<=ext_lraw when i=0 else std_logic_vector(raw);
    rx_rraw<=ext_rraw when i=count-1 else std_logic_vector(raw);
    first_drop:if i=0 generate dl<=ext_ldrop;end generate;
    other_drop:if i>0 generate dl<=unsigned(fdrop(i-1));end generate;
    dr<=ext_rdrop when i=count-1 else unsigned(bdrop(i));dropped_o(i)<=std_logic_vector(dl+dr);
    rrx(i)<=ext_rd when i=count-1 else bd(i);rrk(i)<=ext_rk when i=count-1 else bk(i);
    rrv(i)<=ext_rv when i=count-1 else bv(i);rrl(i)<=ext_rl when i=count-1 else bl(i);
    rready(i)<=right_tx_ready_i when i=count-1 else fr(i);
    has_left:if i>0 generate
      lrx(i)<=fd(i-1);lrk(i)<=fk(i-1);lrv(i)<=fv(i-1);lrl(i)<=fl(i-1);lready(i)<=br(i-1);
    end generate;
    u:entity work.sync_system generic map(G_NODES=>G_MAX_NODES,G_MODE=>2,G_ARM_DELAY_CYCLES=>G_ARM_DELAY,
      G_RUN_CYCLES=>0,G_RUNTIME_CONFIG=>true,G_EXTERNAL_SCHEDULER=>true,G_RUNTIME_TIMING=>true)
      port map(clk_i=>clk_i,rst_i=>reset(i),start_i=>start_i and enabled(i),stop_i=>stop_i,
        links_up_i=>links_up_i and enabled(i) and not overflow,data_idle_i=>'1',
        left_rx_data_i=>lrx(i),left_rx_keep_i=>lrk(i),left_rx_valid_i=>lrv(i),left_rx_last_i=>lrl(i),
        right_rx_data_i=>rrx(i),right_rx_keep_i=>rrk(i),right_rx_valid_i=>rrv(i),right_rx_last_i=>rrl(i),
        left_tx_data_o=>ld(i),left_tx_keep_o=>lk(i),left_tx_valid_o=>lv(i),left_tx_last_o=>ll(i),left_tx_ready_i=>lready(i),
        right_tx_data_o=>rd(i),right_tx_keep_o=>rk(i),right_tx_valid_o=>rv(i),right_tx_last_o=>rl(i),right_tx_ready_i=>rready(i),
        launch_o=>open,cycle_id_o=>open,running_o=>running_o(i),sync_locked_o=>locked_o(i),management_o=>open,
        raw_counter_o=>open,logical_time_o=>times(i),offset_o=>corrections_o(i),path_delay_o=>delays_o(i),sync_window_miss_o=>open,error_o=>errors_o(i),
        config_mode_i=>2,config_nodes_i=>nodes_i,config_id_i=>id,
        external_raw_i=>std_logic_vector(raw),left_rx_raw_i=>rx_lraw,right_rx_raw_i=>rx_rraw,
        left_rx_time_i=>times(i),right_rx_time_i=>times(i),busy_o=>busy(i),holdover_o=>holdover_o(i),
        audit_left_o=>audits_left_o(i),audit_right_o=>audits_right_o(i),
        logical_step_i=>steps_i(i),initial_offset_i=>offsets_i(i),period_cycles_i=>period_i,sync_interval_i=>interval_i,
        theta_o=>theta_o(i),accepted_age_o=>ages_o(i),accepted_count_o=>accepted_o(i),rejected_count_o=>rejected_o(i),deferred_count_o=>deferred_o(i),idle_o=>idle(i));
    marker:entity work.ptp_epoch_marker port map(clk_i,reset(i),running_o(i),times(i),epoch_i,period_i,width_i,
      pulses_o(i),marker_idx,skipped,backsteps);
    marker_indices_o(i)<=std_logic_vector(marker_idx);skipped_o(i)<=std_logic_vector(skipped);backsteps_o(i)<=std_logic_vector(backsteps);
  end generate;
  edges:for i in 0 to G_CAPACITY-2 generate
    signal edge_reset:std_logic;
    signal df,db:unsigned(31 downto 0);
  begin
    edge_reset<=link_reset or not enabled(i+1);
    forward_link:entity work.ptp_neighbor_link port map(clk_i,edge_reset,forward_i(i+1),jitter_i,
      seed_i+to_unsigned(2*i+1,32),drop_every_i,rd(i),rk(i),rv(i) and enabled(i+1),rl(i),fr(i),
      fd(i),fk(i),fv(i),fl(i),link_idle_f(i),df);
    reverse_link:entity work.ptp_neighbor_link port map(clk_i,edge_reset,reverse_i(i),jitter_i,
      seed_i+to_unsigned(2*i+2,32),drop_every_i,ld(i+1),lk(i+1),lv(i+1) and enabled(i+1),ll(i+1),br(i),
      bd(i),bk(i),bv(i),bl(i),link_idle_r(i),db);
    fdrop(i)<=std_logic_vector(df);bdrop(i)<=std_logic_vector(db);
  end generate;
  bd(G_CAPACITY-1)<=(others=>'0');bk(G_CAPACITY-1)<="11";
  process(all)
    variable quiet:std_logic;
  begin
    quiet:=ext_li and ext_ri;
    for i in 0 to G_CAPACITY-1 loop
      if i<count then quiet:=quiet and idle(i) and link_idle_f(i) and link_idle_r(i);end if;
    end loop;idle_o<=quiet;
  end process;
end;
