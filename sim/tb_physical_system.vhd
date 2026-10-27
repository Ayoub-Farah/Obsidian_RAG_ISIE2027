library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;
use work.benchmark_pkg.all;
use work.physical_pkg.all;
entity tb_physical_system is generic(G_TEST_PAGES:boolean:=false;G_TEST_HOLDOVER:boolean:=false);end;
architecture test of tb_physical_system is
  type a64 is array(0 to 2) of std_logic_vector(63 downto 0);
  type a256 is array(0 to 2) of std_logic_vector(255 downto 0);
  type configs_t is array(0 to 2) of config_t;
  signal clocks:std_logic_vector(0 to 2):=(others=>'0');
  signal rst:std_logic:='1';signal resets:std_logic_vector(0 to 2):=(others=>'1');
  signal configure,start,stop_run,ack:std_logic_vector(0 to 2):=(others=>'0');
  signal cfg:config_t:=C_DEFAULT_CONFIG;signal active_cfg:configs_t;
  signal cfg_b:config_t:=C_DEFAULT_CONFIG;signal mismatch:boolean:=false;signal shadows:configs_t;
  signal ld,rd,lr,rr:word_array_t(0 to 2);signal lk,rk,lrk,rrk:keep_array_t(0 to 2);
  signal lv,rv,ll,rl,lready,rready,lrv,rrv,lrl,rrl:std_logic_vector(0 to 2);
  signal status:a256;signal raw,logical,logs,lost:a64;
  signal address:unsigned(12 downto 0):=(others=>'0');
  signal oracle_first,oracle_last:unsigned(63 downto 0):=(others=>'0');
begin
  clocks(0)<=not clocks(0) after 8 ns;
  clocks(1)<=not clocks(1) after 8.000016 ns;
  clocks(2)<=not clocks(2) after 7.999984 ns;
  boards:for b in 0 to 2 generate
    constant PREV:natural:=(b+2) mod 3;constant NEXT_BOARD:natural:=(b+1) mod 3;
  begin
    shadows(b)<=cfg_b when b=1 and mismatch else cfg;
    dut:entity work.physical_system generic map(G_SYNC_ARM_DELAY=>10000)
      port map(clk_i=>clocks(b),rst_i=>resets(b),links_up_i=>'1',link_fault_i=>'0',
        configure_i=>configure(b),start_i=>start(b),stop_i=>stop_run(b),page_ack_i=>ack(b),config_i=>shadows(b),role_i=>to_unsigned(b,2),
        left_rx_data_i=>lr(b),right_rx_data_i=>rr(b),left_rx_keep_i=>lrk(b),right_rx_keep_i=>rrk(b),
        left_rx_valid_i=>lrv(b),left_rx_last_i=>lrl(b),right_rx_valid_i=>rrv(b),right_rx_last_i=>rrl(b),
        left_tx_data_o=>ld(b),right_tx_data_o=>rd(b),left_tx_keep_o=>lk(b),right_tx_keep_o=>rk(b),
        left_tx_valid_o=>lv(b),left_tx_last_o=>ll(b),right_tx_valid_o=>rv(b),right_tx_last_o=>rl(b),left_tx_ready_i=>lready(b),right_tx_ready_i=>rready(b),
        status_o=>status(b),raw_o=>raw(b),logical_o=>logical(b),active_o=>active_cfg(b),log_addr_i=>address,log_data_o=>logs(b),lost_o=>lost(b));
    fw:entity work.physical_link_model generic map(G_PHASE=>17+b*71)
      port map(clocks(b),clocks(NEXT_BOARD),rst,rd(b),rk(b),rv(b),rl(b),rready(b),lr(NEXT_BOARD),lrk(NEXT_BOARD),lrv(NEXT_BOARD),lrl(NEXT_BOARD));
    reverse_path:entity work.physical_link_model generic map(G_PHASE=>31+b*91)
      port map(clocks(b),clocks(PREV),rst,ld(b),lk(b),lv(b),ll(b),lready(b),rr(PREV),rrk(PREV),rrv(PREV),rrl(PREV));
    monotonic:process(clocks(b))
      variable previous:unsigned(63 downto 0):=(others=>'0');variable initialized:boolean:=false;
      variable left_index,right_index:natural range 0 to 2:=0;
      variable left_magic,right_magic:std_logic_vector(15 downto 0):=(others=>'0');
      variable tx_index:natural range 0 to 2:=0;
      variable tx_magic:std_logic_vector(15 downto 0):=(others=>'0');
      variable tx_first_raw,last_rx_raw:ticks_t:=(others=>'0');
      variable input_active:boolean:=false;
      variable data_active:boolean;
    begin if rising_edge(clocks(b)) then
      if resets(b)='1' then initialized:=false;left_index:=0;right_index:=0;tx_index:=0;input_active:=false;
      else
        if initialized then assert unsigned(raw(b))=previous+1 report "Raw counter changed across runtime configuration" severity failure;end if;
        previous:=unsigned(raw(b));initialized:=true;
        assert status(b)(12)='0' report "Controller fault b="&integer'image(b)&" status="&to_hstring(status(b)) severity failure;
        data_active:=status(0)(11)='1' and ((cfg_mode(active_cfg(0))=C_CT and status(0)(27 downto 25)/="001") or
                     (cfg_mode(active_cfg(0))=C_RAG and status(0)(27 downto 25)/="111"));
        if lrv(b)='1' then
          input_active:=true;
          if lrl(b)='1' then input_active:=false;last_rx_raw:=unsigned(raw(b));end if;
          if left_index=0 then left_magic:=lr(b);left_index:=1;
          elsif left_index=1 then
            assert not(data_active and left_magic=x"C35A" and lr(b)(15 downto 8)=x"01") report "Sync maintenance during live DATA" severity failure;
            left_index:=2;
          end if;
          if lrl(b)='1' then left_index:=0;end if;
        end if;
        if rv(b)='1' and rready(b)='1' then
          if tx_index=0 then
            tx_magic:=rd(b);tx_first_raw:=unsigned(raw(b));tx_index:=1;
          elsif tx_index=1 then
            if b>0 and cfg_mode(active_cfg(b))=C_CT and tx_magic=x"C35A" and rd(b)(15 downto 8)=x"02" then
              assert input_active or tx_first_raw<last_rx_raw
                report "CT first accepted TX must precede last physical RX, including minimum payload; b="&integer'image(b)
                severity failure;
            end if;
            tx_index:=2;
          end if;
          if rl(b)='1' then tx_index:=0;end if;
        end if;
        if rrv(b)='1' then
          if right_index=0 then right_magic:=rr(b);right_index:=1;
          elsif right_index=1 then
            assert not(data_active and right_magic=x"C35A" and rr(b)(15 downto 8)=x"01") report "Reverse sync maintenance during live DATA" severity failure;
            right_index:=2;
          end if;
          if rrl(b)='1' then right_index:=0;end if;
        end if;
      end if;
    end if;end process;
  end generate;
  oracle:process(clocks(0))
    variable txactive,rxactive,rxdata:boolean:=false;variable rxwords:natural:=0;
  begin if rising_edge(clocks(0)) then
    if resets(0)='1' then txactive:=false;rxactive:=false;
    else
      if rv(0)='1' and rready(0)='1' then
        if not txactive and rd(0)=x"C35A" and status(0)(11)='1' and cfg_mode(active_cfg(0))=C_CT then oracle_first<=unsigned(raw(0));end if;
        txactive:=rl(0)/='1';
      end if;
      if lrv(0)='1' then
        if not rxactive then rxwords:=0;rxdata:=false;end if;
        if rxwords=1 then rxdata:=lr(0)(15 downto 8)=x"02";end if;
        rxwords:=rxwords+1;rxactive:=lrl(0)/='1';
        if lrl(0)='1' and rxdata then oracle_last<=unsigned(raw(0));end if;
      end if;
    end if;
  end if;end process;
  process
    variable ok:boolean;variable row,row_b,row_c:summary_t;variable before_raw:unsigned(63 downto 0);
    procedure ticks(n:positive) is begin for k in 1 to n loop wait until rising_edge(clocks(0));end loop;wait for 1 ns;end;
    procedure pulse(signal cmd:out std_logic_vector(0 to 2);value:std_logic_vector(0 to 2)) is
    begin wait until falling_edge(clocks(0));cmd<=value;ticks(3);wait until falling_edge(clocks(0));cmd<="000";end;
    procedure apply(c:config_t) is
    begin
      before_raw:=unsigned(raw(0));cfg<=c;pulse(configure,"111");ok:=false;
      for k in 0 to 500000 loop
        ticks(1);ok:=true;
        for b in 0 to 2 loop if active_cfg(b)/=c or status(b)(8)/='1' then ok:=false;end if;end loop;
        exit when ok;
      end loop;
      assert ok report "Distributed config timeout A="&to_hstring(status(0))&" B="&to_hstring(status(1))&" C="&to_hstring(status(2)) severity failure;
      assert unsigned(raw(0))>before_raw report "Config reset the measurement clock" severity failure;
    end;
    procedure run_and_read is
      variable stopped_during_prepare:boolean:=false;
    begin
      pulse(start,"100");ok:=false;
      for k in 0 to 1000000 loop
        ticks(1);ok:=status(0)(18)='1' and status(1)(18)='1' and status(2)(18)='1';exit when ok;
        if cfg_hops(cfg)=4096 and not stopped_during_prepare and unsigned(status(0)(127 downto 96))=1 and
          unsigned(status(0)(7 downto 0))=7 and status(1)(17)='1' then
          pulse(stop_run,"100");stopped_during_prepare:=true;
        end if;
      end loop;
      assert ok report "Run/page timeout A="&to_hstring(status(0))&" B="&to_hstring(status(1))&" C="&to_hstring(status(2)) severity failure;
      address<=to_unsigned(7169,13);ticks(4);
      for b in 0 to 2 loop assert unsigned(logs(b)(47 downto 32))=unsigned(cfg(127 downto 96)) report "Wrong summary count" severity failure;end loop;
      for record_index in 0 to to_integer(unsigned(cfg(127 downto 96)))-1 loop
        for w in 0 to 31 loop address<=to_unsigned(record_index*32+w,13);ticks(4);
          row(64*w+63 downto 64*w):=logs(0);row_b(64*w+63 downto 64*w):=logs(1);row_c(64*w+63 downto 64*w):=logs(2);
        end loop;
        assert row(226)='0' and row(227)='0' and row_b(226)='0' and row_c(226)='0' report "Invalid summary" severity failure;
        if cfg_mode(cfg)=C_CT and unsigned(cfg(127 downto 96))=1 then
          assert unsigned(row(1727 downto 1664))=oracle_last-oracle_first report "RTT not measured at actual Aurora handshakes" severity failure;
        end if;
        report "PHYS_SUMMARY,A,"&to_hstring(row);report "PHYS_SUMMARY,B,"&to_hstring(row_b);report "PHYS_SUMMARY,C,"&to_hstring(row_c);
      end loop;
      report "PHYSICAL_SYSTEM_PASS mode="&integer'image(cfg_mode(cfg))&" P="&integer'image(cfg_payload(cfg))&" H="&integer'image(cfg_hops(cfg));
      if cfg_hops(cfg)=4096 then
        assert row_b(1248)='1' report "Long transfer holdover not recorded on follower" severity failure;
        assert stopped_during_prepare report "STOP during held prepare was not exercised" severity failure;
      end if;
      if unsigned(cfg(159 downto 128))=625000 then
        assert row_b(1248)='0' and row_b(1250)='0' report "Maintenance was disabled throughout a long idle trial period" severity failure;
      end if;
      pulse(ack,"111");ticks(100);
    end;
  begin
    wait for 128 ns;rst<='0';resets(0)<='0';wait for 96 ns;resets(1)<='0';wait for 128 ns;resets(2)<='0';ticks(20);
    apply(make_config(1,4096,6,2,C_CT,to_unsigned(1,32),to_unsigned(6250,32)));run_and_read;
    apply(make_config(2,257,6,4,C_RAG,to_unsigned(3,32),to_unsigned(1000,32)));run_and_read;
    apply(make_config(3,4095,1365,2,C_CT,to_unsigned(1,32),to_unsigned(6250,32)));run_and_read;
    apply(make_config(13,3,1,2,C_CT,to_unsigned(1,32),to_unsigned(6250,32)));run_and_read;
    -- Change config and stop while the old CT payload is still in flight.
    apply(make_config(4,4096,6,2,C_CT,to_unsigned(0,32),to_unsigned(6250,32)));
    pulse(start,"100");
    for k in 0 to 100000 loop ticks(1);exit when status(0)(11)='1';end loop;
    ticks(100);cfg<=make_config(5,17,3,2,C_RAG,to_unsigned(1,32),to_unsigned(6250,32));
    pulse(configure,"111");pulse(stop_run,"100");ok:=false;
    for k in 0 to 100000 loop ticks(1);ok:=status(0)(18)='1' and status(1)(18)='1' and status(2)(18)='1';exit when ok;end loop;
    assert ok report "Config during frame failed to drain/freeze" severity failure;
    for b in 0 to 2 loop assert active_cfg(b)(31 downto 0)=x"00000004" report "Config committed before old page was drained" severity failure;end loop;
    pulse(ack,"111");ok:=false;
    for k in 0 to 100000 loop ticks(1);ok:=active_cfg(0)=cfg and active_cfg(1)=cfg and active_cfg(2)=cfg;exit when ok;end loop;
    assert ok report "Deferred configuration did not commit" severity failure;run_and_read;
    if G_TEST_PAGES then
      apply(make_config(6,1,1,1,C_RAG,to_unsigned(129,32),to_unsigned(1250,32)));
      pulse(start,"100");
      for page in 0 to 1 loop
        ok:=false;for k in 0 to 2000000 loop ticks(1);ok:=status(0)(18)='1' and status(1)(18)='1' and status(2)(18)='1';exit when ok;end loop;
        assert ok report "Paged run timeout" severity failure;
        address<=to_unsigned(7169,13);ticks(4);
        for b in 0 to 2 loop
          if page=0 then assert unsigned(logs(b)(47 downto 32))=128 report "First page incomplete" severity failure;
          else assert unsigned(logs(b)(47 downto 32))=1 report "Remainder page incomplete" severity failure;end if;
        end loop;
        -- Keep the page frozen while idle maintenance proceeds.
        address<=to_unsigned(7168,13);ticks(4);before_raw:=unsigned(logs(0));ticks(70000);
        assert unsigned(logs(0))=before_raw report "Frozen page changed" severity failure;
        if page=0 then
          -- A slow VIO transaction may keep ACK high beyond the next trial.
          -- That must release only this page, not erase the next frozen page.
          wait until falling_edge(clocks(0));ack<="111";ticks(70000);
          for b in 0 to 2 loop assert status(b)(18)='1' report "Held JTAG ACK erased the following page" severity failure;end loop;
          wait until falling_edge(clocks(0));ack<="000";ticks(100);
        else pulse(ack,"111");ticks(100);end if;
      end loop;
      assert unsigned(status(0)(127 downto 96))=129 report "Paging lost repetitions" severity failure;
    end if;
    if G_TEST_HOLDOVER then
      apply(make_config(8,1,1,4096,C_RAG,to_unsigned(2,32),to_unsigned(6250,32)));run_and_read;
      apply(make_config(11,17,3,2,C_CT,to_unsigned(2,32),to_unsigned(625000,32)));run_and_read;
    end if;
    -- Disagreeing cards reject the transaction without changing any active bank.
    before_raw:=resize(unsigned(active_cfg(0)(31 downto 0)),64);
    cfg<=make_config(9,17,3,2,C_RAG,to_unsigned(1,32),to_unsigned(6250,32));
    cfg_b<=make_config(9,18,3,2,C_RAG,to_unsigned(1,32),to_unsigned(6250,32));mismatch<=true;pulse(configure,"111");
    ok:=false;for k in 0 to 100000 loop ticks(1);ok:=status(0)(10)='1';exit when ok;end loop;
    assert ok report "Disagreeing config accepted" severity failure;
    for b in 0 to 2 loop assert unsigned(active_cfg(b)(31 downto 0))=before_raw report "Partial config commit" severity failure;end loop;
    mismatch<=false;apply(make_config(10,17,3,2,C_RAG,to_unsigned(1,32),to_unsigned(6250,32)));
    -- Idle STOP seals a calibration-only page on all three cards.
    ticks(1000);pulse(stop_run,"100");ok:=false;
    for k in 0 to 100000 loop ticks(1);ok:=status(0)(18)='1' and status(1)(18)='1' and status(2)(18)='1';exit when ok;end loop;
    assert ok report "Idle STOP did not seal three calibration pages" severity failure;
    pulse(ack,"111");ticks(100);
    -- Invalid shadow values must leave active configuration unchanged.
    before_raw:=resize(unsigned(active_cfg(0)(31 downto 0)),64);
    cfg<=make_config(7,2,1,2,C_CT,to_unsigned(1,32),to_unsigned(6250,32));pulse(configure,"111");ticks(200);
    for b in 0 to 2 loop assert status(b)(10)='1' and unsigned(active_cfg(b)(31 downto 0))=before_raw report "Invalid config committed" severity failure;end loop;
    report "PASS tb_physical_system";stop;wait;
  end process;
end;
