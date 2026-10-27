-- Three-board coordinator. Tokens are forwarded in the physical A->B->C->A
-- ring; retirement counts, not a silence interval, prove global completion.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.benchmark_pkg.all;
use work.physical_pkg.all;
entity physical_controller is
  generic(G_ARM_GUARD:positive:=1024;G_CONTROL_TIMEOUT:positive:=16777215);
  port(clk_i,rst_i:in std_logic;raw_i:in ticks_t;logical_i:in std_logic_vector(63 downto 0);
    links_i,link_fault_i:in std_logic;
    shadow_i:in config_t;role_i:in unsigned(1 downto 0);
    configure_i,start_i,stop_i,page_ack_i:in std_logic;
    active_o:out config_t;board_o:out unsigned(1 downto 0);configured_o:out std_logic;
    sync_running_i,sync_locked_i,sync_busy_i,sync_holdover_i:in std_logic;
    sync_start_o,maintenance_o:out std_logic;
    node_idle_i,node_fault_i,removed_i:in std_logic;
    removed_origin_i:in unsigned(1 downto 0);removed_hops_i:in unsigned(15 downto 0);removed_bad_i:in std_logic;
    node_start_o:out std_logic;run_o,trial_o:out std_logic_vector(31 downto 0);
    journal_frozen_i,journal_busy_i:in std_logic;summary_count_i:in unsigned(7 downto 0);
    summary_o,freeze_o:out std_logic;skipped_o:out ticks_t;epoch_o:out ticks_t;
    rx_event_i,rx_error_i:in std_logic;rx_kind_i:in byte_t;rx_seq_i:in std_logic_vector(31 downto 0);
    rx_time_i:in std_logic_vector(63 downto 0);rx_payload_i:in control_payload_t;
    tx_ready_i:in std_logic;tx_request_o:out std_logic;tx_kind_o:out byte_t;
    tx_seq_o:out std_logic_vector(31 downto 0);tx_time_o:out std_logic_vector(63 downto 0);tx_payload_o:out control_payload_t;
    status_o:out std_logic_vector(255 downto 0));
end;
architecture rtl of physical_controller is
  type state_t is (IDLE,CFG_SEND,CFG_WAIT,COMMIT_SEND,COMMIT_WAIT,SYNC_WAIT,PREP_SEND,PREP_WAIT,QUIESCE_SEND,QUIESCE_WAIT,
    ALIGN_EPOCH,ARM_SEND,ARM_WAIT,GO_SEND,GO_WAIT,WAIT_EPOCH,TRANSFER,DRAIN_SEND,DRAIN_WAIT,
    RELEASE_SEND,RELEASE_WAIT,PAGE_WAIT,FAULTED);
  signal state:state_t:=IDLE;
  signal active,pending_cfg:config_t:=C_DEFAULT_CONFIG;
  signal board:unsigned(1 downto 0):="11";
  signal configured,cfg_pending,cfg_prepared,invalid_config,maintenance:std_logic:='0';
  signal want_run,stop_pending,run_finished,trial_live,armed,staged:std_logic:='0';
  signal run_id,trial_id,completed:unsigned(31 downto 0):=(others=>'0');
  signal epoch,grid,skipped:ticks_t:=(others=>'0');
  signal retire_mask:std_logic_vector(2 downto 0):=(others=>'0');
  signal trial_error,sticky_fault:std_logic:='0';
  signal watchdog:natural range 0 to G_CONTROL_TIMEOUT:=0;
  signal previous_commands:std_logic_vector(3 downto 0):=(others=>'0');
  -- The queue can absorb simultaneous retirement and token forwarding.
  type q_t is array(0 to 7) of std_logic_vector(423 downto 0);
  signal q:q_t;signal qr,qw:natural range 0 to 7:=0;signal qu:natural range 0 to 8:=0;
  signal offered:std_logic:='0';
  signal retire_pending,stop_message_pending:std_logic:='0';
  signal stop_freeze_pending:std_logic:='0';
  signal force_prepare:std_logic:='0';
  signal pending_origin:unsigned(1 downto 0):=(others=>'0');
  signal pending_hops:unsigned(15 downto 0):=(others=>'0');signal pending_bad:std_logic:='0';
  signal deferred:std_logic:='0';signal dk:byte_t;signal ds:std_logic_vector(31 downto 0);
  signal dtime:std_logic_vector(63 downto 0);signal dp:control_payload_t;
  -- Sequential restoring division aligns to the existing period grid without
  -- synthesizing a large combinational / operator or iterating billions of ticks.
  signal dividend:ticks_t:=(others=>'0');signal remainder:unsigned(64 downto 0):=(others=>'0');
  signal quotient:ticks_t:=(others=>'0');signal align_target:ticks_t:=(others=>'0');
  signal division_bit:natural range 0 to 64:=64;
  function advance(v:natural) return natural is begin if v=7 then return 0;else return v+1;end if;end;
begin
  active_o<=active;board_o<=board;configured_o<=configured;
  maintenance_o<=maintenance and configured;
  run_o<=std_logic_vector(run_id);trial_o<=std_logic_vector(trial_id);skipped_o<=skipped;epoch_o<=epoch;
  tx_kind_o<=q(qr)(423 downto 416);tx_seq_o<=q(qr)(415 downto 384);
  tx_time_o<=q(qr)(383 downto 320);tx_payload_o<=q(qr)(319 downto 0);
  process(all)
    variable s:std_logic_vector(255 downto 0);
  begin
    s:=(others=>'0');s(7 downto 0):=std_logic_vector(to_unsigned(state_t'pos(state),8));
    s(8):=configured;s(9):=cfg_pending;s(10):=invalid_config;s(11):=trial_live;s(12):=sticky_fault;
    s(13):=want_run;s(14):=sync_running_i;s(15):=sync_locked_i;s(16):=sync_busy_i;s(17):=sync_holdover_i;
    s(18):=journal_frozen_i;s(19):=maintenance;s(20):=node_idle_i;s(21):=node_fault_i;s(22):=trial_error;
    s(24 downto 23):=std_logic_vector(board);s(27 downto 25):=retire_mask;
    s(31 downto 28):=std_logic_vector(to_unsigned(qu,4));s(63 downto 32):=active(31 downto 0);
    s(95 downto 64):=std_logic_vector(run_id);s(127 downto 96):=std_logic_vector(completed);
    s(159 downto 128):=std_logic_vector(trial_id);s(223 downto 160):=std_logic_vector(skipped);
    s(231 downto 224):=std_logic_vector(summary_count_i);s(255 downto 232):=x"504803";
    status_o<=s;
  end process;
  process(clk_i)
    variable count,wp,rp,bi,oi:natural;
    variable p:control_payload_t;variable kind:byte_t;variable seq:std_logic_vector(31 downto 0);
    variable time_value:std_logic_vector(63 downto 0);variable process_message,can_forward:boolean;
    variable commands,edges:std_logic_vector(3 downto 0);
    variable now_ticks,period,target,delta,new_epoch:ticks_t;
    variable rem_next:unsigned(64 downto 0);variable qnext:ticks_t;
    variable expected_mask:std_logic_vector(2 downto 0);
    variable near_grid:boolean;
    variable enqueue_valid:boolean;variable enqueue_word:std_logic_vector(423 downto 0);
    procedure send(k:byte_t;payload:control_payload_t;stamp:std_logic_vector(63 downto 0);sn:std_logic_vector(31 downto 0)) is
    begin
      assert not enqueue_valid report "Two scheduled token writes in one cycle" severity failure;
      if not enqueue_valid then enqueue_word:=k & sn & stamp & payload;enqueue_valid:=true;
      else sticky_fault<='1';state<=FAULTED;end if;
    end procedure;
    procedure base_payload(variable v:out control_payload_t) is
    begin
      v:=(others=>'0');v(159 downto 0):=active;
      v(191 downto 160):=std_logic_vector(run_id);v(223 downto 192):=std_logic_vector(trial_id);
      v(226 downto 224):="001";v(319 downto 256):=std_logic_vector(skipped);
    end procedure;
  begin if rising_edge(clk_i) then
    node_start_o<='0';sync_start_o<='0';summary_o<='0';freeze_o<='0';tx_request_o<='0';
    commands:=page_ack_i & stop_i & start_i & configure_i;edges:=commands and not previous_commands;previous_commands<=commands;
    if rst_i='1' then
      state<=IDLE;active<=C_DEFAULT_CONFIG;pending_cfg<=C_DEFAULT_CONFIG;board<="11";
      configured<='0';cfg_pending<='0';cfg_prepared<='0';invalid_config<='0';maintenance<='0';
      want_run<='0';stop_pending<='0';run_finished<='0';trial_live<='0';armed<='0';staged<='0';
      run_id<=(others=>'0');trial_id<=(others=>'0');completed<=(others=>'0');skipped<=(others=>'0');grid<=(others=>'0');
      sticky_fault<='0';trial_error<='0';retire_mask<=(others=>'0');qr<=0;qw<=0;qu<=0;offered<='0';deferred<='0';
      previous_commands<=(others=>'0');watchdog<=0;division_bit<=64;
      retire_pending<='0';stop_message_pending<='0';
      stop_freeze_pending<='0';
      force_prepare<='0';
    else
      count:=qu;wp:=qw;rp:=qr;bi:=to_integer(board);
      enqueue_valid:=false;enqueue_word:=(others=>'0');
      now_ticks:=shift_right(unsigned(logical_i),16);period:=resize(unsigned(active(159 downto 128)),64);
      near_grid:=grid=0 or grid<=now_ticks+4*G_ARM_GUARD;
      if offered='1' then
        offered<='0';if count>0 then rp:=advance(qr);count:=count-1;end if;
      elsif qu>0 and tx_ready_i='1' then tx_request_o<='1';offered<='1';end if;
      -- No command changes an engaged frame or resets the raw counter.
      if edges(0)='1' then
        if valid_config(shadow_i) and role_i/="11" and (configured='0' or role_i=board) then
          pending_cfg<=shadow_i;cfg_pending<='1';cfg_prepared<='0';invalid_config<='0';stop_pending<='1';want_run<='0';
          if configured='0' then board<=role_i;end if;
        else invalid_config<='1';end if;
      end if;
      if edges(2)='1' then
        stop_pending<='1';want_run<='0';
        if trial_live='0' and state=IDLE then freeze_o<='1';end if;
        if board/="11" then
          stop_message_pending<='1';
          if board="00" and (state=IDLE or state=PAGE_WAIT) then stop_freeze_pending<='1';end if;
        end if;
      end if;
      if edges(1)='1' and board="00" and configured='1' and cfg_pending='0' and state=IDLE and journal_frozen_i='0' and summary_count_i=0 then
        want_run<='1';stop_pending<='0';run_finished<='0';run_id<=run_id+1;trial_id<=(others=>'0');completed<=(others=>'0');
        skipped<=(others=>'0');grid<=(others=>'0');state<=SYNC_WAIT;maintenance<='1';
        force_prepare<='0';
        if sync_running_i='0' then sync_start_o<='1';end if;
      end if;
      -- Count nominal grid deadlines independently of serialization duration.
      if board="00" and want_run='1' and grid/=0 and now_ticks>=grid and state/=ALIGN_EPOCH then
        grid<=grid+period;skipped<=skipped+1;
      end if;
      if armed='1' and unsigned(logical_i)>=shift_left(epoch,16) then
        armed<='0';
        if unsigned(logical_i)-shift_left(epoch,16)<to_unsigned(8*65536,64) and links_i='1' then
          node_start_o<='1';trial_live<='1';retire_mask<=(others=>'0');trial_error<='0';
          if board="00" then state<=TRANSFER;end if;
        else sticky_fault<='1';state<=FAULTED;end if;
      end if;
      if removed_i='1' then
        oi:=to_integer(removed_origin_i);
        if trial_live='0' or oi>2 then sticky_fault<='1';state<=FAULTED;
        else
          if board="00" then
            if retire_mask(oi)='1' then sticky_fault<='1';state<=FAULTED;end if;
            retire_mask(oi)<='1';trial_error<=trial_error or removed_bad_i;
          else
            if retire_pending='1' then sticky_fault<='1';state<=FAULTED;end if;
            retire_pending<='1';pending_origin<=removed_origin_i;pending_hops<=removed_hops_i;pending_bad<=removed_bad_i;
          end if;
        end if;
      end if;
      -- Followers may hold PREPARE/DRAIN until their local pipelines and sync
      -- transactions finish. This does not stop the independent RX data path.
      process_message:=false;p:=(others=>'0');kind:=x"00";seq:=(others=>'0');time_value:=(others=>'0');
      if deferred='1' then
        p:=dp;kind:=dk;seq:=ds;time_value:=dtime;can_forward:=false;
        if dk=x"32" then
          can_forward:=node_idle_i='1' and sync_running_i='1' and sync_locked_i='1' and sync_holdover_i='0' and sync_busy_i='0' and journal_frozen_i='0' and journal_busy_i='0';
        elsif dk=x"3B" then maintenance<='0';can_forward:=node_idle_i='1' and sync_busy_i='0';
        elsif dk=x"35" then can_forward:=node_idle_i='1';
        elsif dk=x"30" then can_forward:=node_idle_i='1' and trial_live='0' and summary_count_i=0 and journal_frozen_i='0';end if;
        if can_forward then process_message:=true;deferred<='0';end if;
        if rx_event_i='1' then
          if rx_kind_i=x"37" then
            -- STOP is asynchronous to a held readiness/drain token. Retain
            -- that token and forward the stop request through its own latch.
            stop_pending<='1';stop_message_pending<='1';stop_freeze_pending<=stop_freeze_pending or rx_payload_i(0);
            if rx_payload_i(0)='1' and trial_live='0' then freeze_o<='1';maintenance<='1';end if;
          else sticky_fault<='1';state<=FAULTED;end if;
        end if;
      elsif rx_event_i='1' then
        process_message:=true;p:=rx_payload_i;kind:=rx_kind_i;seq:=rx_seq_i;time_value:=rx_time_i;
        if board/="00" then
          can_forward:=true;
          if kind=x"32" then
            maintenance<='1';
            can_forward:=node_idle_i='1' and sync_running_i='1' and sync_locked_i='1' and sync_holdover_i='0' and sync_busy_i='0' and journal_frozen_i='0' and journal_busy_i='0';
          elsif kind=x"3B" then maintenance<='0';can_forward:=node_idle_i='1' and sync_busy_i='0';
          elsif kind=x"35" then can_forward:=node_idle_i='1';
          elsif kind=x"30" then
            can_forward:=node_idle_i='1' and trial_live='0' and summary_count_i=0 and journal_frozen_i='0';
            if summary_count_i/=0 then freeze_o<='1';end if;
          end if;
          if not can_forward then deferred<='1';dk<=kind;dp<=p;ds<=seq;dtime<=time_value;process_message:=false;end if;
        end if;
      end if;
      if process_message then
        if board="00" then
          case kind is
            when x"30" =>
              if state/=CFG_WAIT or p(227)='1' or p(226 downto 224)/="111" or p(159 downto 0)/=pending_cfg then invalid_config<='1';cfg_pending<='0';state<=IDLE;
              else state<=COMMIT_SEND;end if;
            when x"31" =>
              if state=COMMIT_WAIT and p(227)='0' and p(226 downto 224)="111" then
                active<=pending_cfg;configured<='1';cfg_pending<='0';cfg_prepared<='0';stop_pending<='0';maintenance<='1';state<=IDLE;
                if sync_running_i='0' then sync_start_o<='1';end if;
              else sticky_fault<='1';state<=FAULTED;end if;
            when x"32" =>
              if state=PREP_WAIT and p(227)='0' and p(226 downto 224)="111" then
                if near_grid then maintenance<='0';state<=QUIESCE_SEND;
                else maintenance<='1';state<=PREP_SEND;end if;
              else sticky_fault<='1';state<=FAULTED;end if;
            when x"3B" =>
              if state=QUIESCE_WAIT and p(227)='0' and p(226 downto 224)="111" then
                if not near_grid then
                  maintenance<='1';force_prepare<='1';state<=PREP_SEND;
                elsif grid=0 then epoch<=now_ticks+G_ARM_GUARD;state<=ARM_SEND;
                else
                  target:=now_ticks+G_ARM_GUARD;align_target<=target;
                  if grid>=target then epoch<=grid;state<=ARM_SEND;
                  else dividend<=target-grid;remainder<=(others=>'0');quotient<=(others=>'0');division_bit<=64;state<=ALIGN_EPOCH;end if;
                end if;
              elsif state=QUIESCE_WAIT then
                -- A mapping can age out while the quiet token circulates.
                -- No data is armed: re-open maintenance and obtain fresh ACKs.
                maintenance<='1';force_prepare<='1';state<=PREP_SEND;
              else sticky_fault<='1';state<=FAULTED;end if;
            when x"33" => if state=ARM_WAIT then state<=GO_SEND;else sticky_fault<='1';state<=FAULTED;end if;
            when x"39" => if state=GO_WAIT then armed<='1';state<=WAIT_EPOCH;else sticky_fault<='1';state<=FAULTED;end if;
            when x"34" =>
              oi:=to_integer(unsigned(p(1 downto 0)));
              if state/=TRANSFER or oi>2 or p(63 downto 32)/=active(31 downto 0) or p(191 downto 160)/=std_logic_vector(run_id) or p(223 downto 192)/=std_logic_vector(trial_id) then
                sticky_fault<='1';state<=FAULTED;
              elsif retire_mask(oi)='1' then sticky_fault<='1';state<=FAULTED;
              else
                if cfg_mode(active)/=C_RAG or unsigned(p(31 downto 16))/=to_unsigned(cfg_hops(active),16) or
                  to_integer(unsigned(p(5 downto 4)))/=(oi+(cfg_hops(active) mod 3)) mod 3 then sticky_fault<='1';state<=FAULTED;
                else retire_mask(oi)<='1';trial_error<=trial_error or p(2);end if;
              end if;
            when x"35" => if state=DRAIN_WAIT and p(226 downto 224)="111" then state<=RELEASE_SEND;else sticky_fault<='1';state<=FAULTED;end if;
            when x"36" =>
              if state=RELEASE_WAIT then
                trial_live<='0';maintenance<='1';
                if p(228)='1' or p(229)='1' then run_finished<=p(228);state<=PAGE_WAIT;
                else trial_id<=trial_id+1;state<=PREP_SEND;end if;
              else sticky_fault<='1';state<=FAULTED;end if;
            when x"37" =>
              stop_pending<='1';want_run<='0';
              if state=IDLE and p(0)='0' then freeze_o<='1';stop_message_pending<='1';stop_freeze_pending<='1';end if;
            when others => sticky_fault<='1';state<=FAULTED;
          end case;
        elsif board/="11" then
          case kind is
            when x"30" =>
              if cfg_pending='0' or pending_cfg/=p(159 downto 0) or not valid_config(p(159 downto 0)) or p(224+bi)='1' then p(227):='1';invalid_config<='1';
              else p(224+bi):='1';cfg_prepared<='1';end if;
              send(kind,p,time_value,seq);
            when x"31" =>
              if cfg_prepared='1' and cfg_pending='1' and pending_cfg=p(159 downto 0) and p(224+bi)='0' then
                active<=pending_cfg;configured<='1';cfg_pending<='0';cfg_prepared<='0';stop_pending<='0';maintenance<='1';p(224+bi):='1';
              else p(227):='1';configured<='0';end if;
              send(kind,p,time_value,seq);
            when x"32" =>
              if configured='0' or active/=p(159 downto 0) or p(224+bi)='1' then p(227):='1';
              else p(224+bi):='1';run_id<=unsigned(p(191 downto 160));trial_id<=unsigned(p(223 downto 192));end if;
              send(kind,p,time_value,seq);
            when x"3B" =>
              maintenance<='0';p(224+bi):='1';
              if sync_locked_i='0' or sync_holdover_i='1' then p(227):='1';end if;
              send(kind,p,time_value,seq);
            when x"33" => epoch<=shift_right(unsigned(time_value),16);staged<='1';send(kind,p,time_value,seq);
            when x"39" =>
              if staged='1' and epoch=shift_right(unsigned(time_value),16) then armed<='1';staged<='0';else sticky_fault<='1';state<=FAULTED;end if;
              send(kind,p,time_value,seq);
            when x"34" => send(kind,p,time_value,seq);
            when x"35" => p(224+bi):='1';send(kind,p,time_value,seq);
            when x"36" =>
              summary_o<='1';completed<=completed+1;trial_live<='0';maintenance<='1';skipped<=unsigned(p(319 downto 256));trial_error<=p(227);
              if p(228)='1' or p(229)='1' then freeze_o<='1';end if;
              send(kind,p,time_value,seq);
            when x"37" => stop_pending<='1';if trial_live='0' and p(0)='1' then freeze_o<='1';maintenance<='1';end if;send(kind,p,time_value,seq);
            when others => sticky_fault<='1';state<=FAULTED;
          end case;
        end if;
      end if;
      if board="00" then
        case state is
          when IDLE =>
            if cfg_pending='1' and trial_live='0' and node_idle_i='1' then
              if summary_count_i/=0 or journal_frozen_i='1' then freeze_o<='1';
              else state<=CFG_SEND;maintenance<='0';end if;
            end if;
          when CFG_SEND =>
            p:=(others=>'0');p(159 downto 0):=pending_cfg;p(226 downto 224):="001";send(x"30",p,(others=>'0'),pending_cfg(31 downto 0));state<=CFG_WAIT;
          when COMMIT_SEND =>
            p:=(others=>'0');p(159 downto 0):=pending_cfg;p(226 downto 224):="001";send(x"31",p,(others=>'0'),pending_cfg(31 downto 0));state<=COMMIT_WAIT;
          when SYNC_WAIT => if sync_running_i='1' and sync_locked_i='1' and sync_holdover_i='0' then state<=PREP_SEND;end if;
          when PREP_SEND =>
            maintenance<='1';
            if stop_pending='1' or cfg_pending='1' then
              want_run<='0';freeze_o<='1';run_finished<='1';state<=PAGE_WAIT;
              stop_message_pending<='1';stop_freeze_pending<='1';
            elsif (near_grid or force_prepare='1') and sync_busy_i='0' and sync_running_i='1' and sync_locked_i='1' and sync_holdover_i='0' and journal_frozen_i='0' and journal_busy_i='0' then
              base_payload(p);send(x"32",p,(others=>'0'),std_logic_vector(trial_id));state<=PREP_WAIT;force_prepare<='0';
            end if;
          when QUIESCE_SEND =>
            maintenance<='0';if sync_busy_i='0' then base_payload(p);send(x"3B",p,(others=>'0'),std_logic_vector(trial_id));state<=QUIESCE_WAIT;end if;
          when ALIGN_EPOCH =>
            if division_bit>0 then
              rem_next:=shift_left(remainder,1);rem_next(0):=dividend(division_bit-1);qnext:=quotient;
              if rem_next>=resize(period,65) then rem_next:=rem_next-resize(period,65);qnext(division_bit-1):='1';end if;
              remainder<=rem_next;quotient<=qnext;division_bit<=division_bit-1;
            else
              if remainder=0 then new_epoch:=align_target;skipped<=skipped+quotient;
              else new_epoch:=align_target+period-resize(remainder,64);skipped<=skipped+quotient+1;end if;
              epoch<=new_epoch;state<=ARM_SEND;
            end if;
          when ARM_SEND =>
            base_payload(p);send(x"33",p,std_logic_vector(shift_left(epoch,16)),std_logic_vector(trial_id));state<=ARM_WAIT;grid<=epoch+period;
          when GO_SEND => base_payload(p);send(x"39",p,std_logic_vector(shift_left(epoch,16)),std_logic_vector(trial_id));state<=GO_WAIT;
          when TRANSFER =>
            expected_mask:="111";if cfg_mode(active)=C_CT then expected_mask:="001";end if;
            if retire_mask=expected_mask and node_idle_i='1' then state<=DRAIN_SEND;end if;
          when DRAIN_SEND => base_payload(p);send(x"35",p,(others=>'0'),std_logic_vector(trial_id));state<=DRAIN_WAIT;
          when RELEASE_SEND =>
            base_payload(p);p(227):=trial_error;
            if stop_pending='1' or cfg_pending='1' or (unsigned(active(127 downto 96))/=0 and completed+1>=unsigned(active(127 downto 96))) then p(228):='1';want_run<='0';end if;
            if summary_count_i>=127 then p(229):='1';end if;
            send(x"36",p,(others=>'0'),std_logic_vector(trial_id));summary_o<='1';completed<=completed+1;
            if p(228)='1' or p(229)='1' then freeze_o<='1';end if;
            state<=RELEASE_WAIT;
          when PAGE_WAIT =>
            if journal_frozen_i='0' and summary_count_i=0 and journal_busy_i='0' then
              if run_finished='1' or cfg_pending='1' then state<=IDLE;want_run<='0';
              else trial_id<=trial_id+1;state<=PREP_SEND;end if;
            end if;
          when others => null;
        end case;
      end if;
      -- Control timeouts never reset/abort an engaged DATA frame. A failed
      -- barrier blocks all future starts until an explicit application reset.
      if state=CFG_WAIT or state=COMMIT_WAIT or state=PREP_WAIT or state=QUIESCE_WAIT or state=ARM_WAIT or state=GO_WAIT or state=DRAIN_WAIT or state=RELEASE_WAIT then
        if watchdog<G_CONTROL_TIMEOUT then watchdog<=watchdog+1;else sticky_fault<='1';state<=FAULTED;end if;
      else watchdog<=0;end if;
      if configured='1' and (links_i='0' or link_fault_i='1' or node_fault_i='1' or rx_error_i='1') then sticky_fault<='1';state<=FAULTED;want_run<='0';maintenance<='0';end if;
      if sticky_fault='1' then state<=FAULTED;want_run<='0';maintenance<='0';armed<='0';end if;
      -- Exactly one queue write port. Local events wait in dedicated latches
      -- when a ring token is forwarded on the same cycle.
      if not enqueue_valid and retire_pending='1' then
        p:=(others=>'0');p(1 downto 0):=std_logic_vector(pending_origin);p(2):=pending_bad;
        p(5 downto 4):=std_logic_vector(board);p(31 downto 16):=std_logic_vector(pending_hops);p(63 downto 32):=active(31 downto 0);
        p(191 downto 160):=std_logic_vector(run_id);p(223 downto 192):=std_logic_vector(trial_id);
        send(x"34",p,(others=>'0'),std_logic_vector(trial_id));retire_pending<='0';
      end if;
      if not enqueue_valid and stop_message_pending='1' then
        p:=(others=>'0');p(0):=stop_freeze_pending;send(x"37",p,(others=>'0'),std_logic_vector(trial_id));stop_message_pending<='0';stop_freeze_pending<='0';
      end if;
      if enqueue_valid then
        if count<8 then q(wp)<=enqueue_word;wp:=advance(wp);count:=count+1;
        else sticky_fault<='1';state<=FAULTED;end if;
      end if;
      qr<=rp;qw<=wp;qu<=count;
    end if;
  end if;end process;
end;
