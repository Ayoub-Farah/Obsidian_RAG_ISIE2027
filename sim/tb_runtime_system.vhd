library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;
use work.benchmark_pkg.all;

-- Complete three-board portable system integration. This models digital
-- transport interfaces only; it does not claim proprietary Aurora-IP coverage.
entity tb_runtime_system is
  generic(G_CAPACITY_LOCAL:positive:=10;G_TEST_RECORDS:positive:=12;G_MAX_ONLY:boolean:=false);
end entity;
architecture test of tb_runtime_system is
  constant C_BOARDS:positive:=3;
  constant C_NODES:positive:=C_BOARDS*G_CAPACITY_LOCAL;
  type a256 is array(0 to C_BOARDS-1) of std_logic_vector(255 downto 0);
  type a512 is array(0 to C_BOARDS-1) of std_logic_vector(511 downto 0);
  type a64 is array(0 to C_BOARDS-1) of std_logic_vector(63 downto 0);
  type a8 is array(0 to C_BOARDS-1) of std_logic_vector(7 downto 0);
  type counts_t is array(0 to C_BOARDS-1) of natural;
  constant G_RECORDS:positive:=G_TEST_RECORDS;
  signal cfg_mode:natural range 0 to 3:=2;
  signal cfg_nodes:natural range 0 to 63:=3;
  type config_counts_t is array(0 to 2) of natural range 0 to 63;
  signal cfg_base:config_counts_t:=(0,1,2);
  signal cfg_local:config_counts_t:=(1,1,1);
  signal invalid_test:boolean:=false;
  signal clk:std_logic:='0'; signal rst:std_logic:='1';
  signal start:std_logic_vector(0 to C_BOARDS-1):=(others=>'0');
  signal stop_run:std_logic:='0';
  signal ld,rd,lr,rr:word_array_t(0 to C_BOARDS-1);
  signal lk,rk,lrk,rrk:keep_array_t(0 to C_BOARDS-1);
  signal lv,rv,ll,rl,lready,rready,lrv,rrv,lrl,rrl:std_logic_vector(0 to C_BOARDS-1);
  signal status:a256;signal raw:a64;signal logs:a512;
  signal log_addr:a8:=(others=>(others=>'0'));
  signal validated:counts_t:=(others=>0);
  signal ticks:natural:=0;
begin
  clk<=not clk after 8 ns;
  boards:for board in 0 to C_BOARDS-1 generate
    constant PREV:natural:=(board+C_BOARDS-1) mod C_BOARDS;
    constant NEXT_BOARD:natural:=(board+1) mod C_BOARDS;
  begin
    dut:entity work.benchmark_system
      generic map(G_MODE=>2,G_NODES=>C_NODES,G_NODE_BASE=>board*G_CAPACITY_LOCAL,
        G_LOCAL_NODES=>G_CAPACITY_LOCAL,G_DATA_BYTES=>6,G_REF_BYTES=>2,
        G_PERIOD_CYCLES=>6250,G_ARM_DELAY_CYCLES=>10000,G_RUN_CYCLES=>G_RECORDS,G_FIFO_WORDS=>128,G_MAX_FRAME_BYTES=>4096,
        G_VLINK_LATENCY=>37,G_VLINK_FIFO_WORDS=>64,G_RUNTIME_CONFIG=>true)
      port map(clk_i=>clk,rst_i=>rst,start_i=>start(board),stop_i=>stop_run,links_up_i=>'1',link_fault_i=>'0',
        left_rx_data_i=>lr(board),left_rx_keep_i=>lrk(board),left_rx_valid_i=>lrv(board),left_rx_last_i=>lrl(board),
        left_tx_data_o=>ld(board),left_tx_keep_o=>lk(board),left_tx_valid_o=>lv(board),left_tx_last_o=>ll(board),left_tx_ready_i=>lready(board),
        right_rx_data_i=>rr(board),right_rx_keep_i=>rrk(board),right_rx_valid_i=>rrv(board),right_rx_last_i=>rrl(board),
        right_tx_data_o=>rd(board),right_tx_keep_o=>rk(board),right_tx_valid_o=>rv(board),right_tx_last_o=>rl(board),right_tx_ready_i=>rready(board),
        status_o=>status(board),raw_counter_o=>raw(board),log_addr_i=>log_addr(board),log_data_o=>logs(board),config_mode_i=>cfg_mode,config_nodes_i=>cfg_nodes,config_base_i=>cfg_base(board),config_local_i=>cfg_local(board));
    forward_link:entity work.virtual_neighbor_link
      generic map(G_LATENCY_CYCLES=>37,G_FIFO_WORDS=>256,G_CC_PHASE=>board*71+11)
      port map(clk,rst,rd(board),rk(board),rv(board),rl(board),rready(board),
        lr(NEXT_BOARD),lrk(NEXT_BOARD),lrv(NEXT_BOARD),lrl(NEXT_BOARD),open,open);
    reverse_link:entity work.virtual_neighbor_link
      generic map(G_LATENCY_CYCLES=>37,G_FIFO_WORDS=>256,G_CC_PHASE=>board*113+19)
      port map(clk,rst,ld(board),lk(board),lv(board),ll(board),lready(board),
        rr(PREV),rrk(PREV),rrv(PREV),rrl(PREV),open,open);
    journal_reader:process(clk)
      variable observed:natural:=0;
      variable pending:natural:=0;
      variable sample:natural:=0;
      variable tuse,tdrain,ttx:unsigned(63 downto 0);
    begin
      if rising_edge(clk) then
        if rst='1' then
          observed:=0;pending:=0;validated(board)<=0;
        elsif pending>0 then
          pending:=pending-1;
          if pending=0 then
            tuse:=unsigned(logs(board)(159 downto 96));
            tdrain:=unsigned(logs(board)(223 downto 160));
            ttx:=unsigned(logs(board)(287 downto 224));
            assert unsigned(logs(board)(31 downto 0))=sample report "Journal cycle mismatch" severity failure;
            assert tuse>0 and tdrain>0 and tuse<=tdrain and tdrain<6250
              report "Invalid local timing journal board="&integer'image(board)&" sample="&integer'image(sample)&" useful="&to_hstring(std_logic_vector(tuse))&" drained="&to_hstring(std_logic_vector(tdrain)) severity failure;
            assert logs(board)(323 downto 320)="0000" and logs(board)(325)='0'
              report "Journal reports failed or incomplete period" severity failure;
            assert logs(board)(327 downto 326)="00" report "Journal transport/link fault" severity failure;
            assert logs(board)(319 downto 288)=x"00000000" report "Journal CRC errors" severity failure;
            assert unsigned(logs(board)(415 downto 400))=cfg_nodes
              and unsigned(logs(board)(399 downto 384))=cfg_local(board)
              and unsigned(logs(board)(383 downto 368))=cfg_base(board)
              report "Journal segment metadata mismatch" severity failure;
            report "BENCH_CSV,"&integer'image(cfg_mode)&","&integer'image(cfg_nodes)&","&integer'image(board)&","&integer'image(sample)&","&integer'image(to_integer(unsigned(logs(board)(95 downto 32))))&","&integer'image(to_integer(tuse))&","&integer'image(to_integer(tdrain))&","&integer'image(to_integer(ttx)) severity note;
            assert logs(board)(328)='1' report "Missing return journal format marker" severity failure;
            assert unsigned(logs(board)(447 downto 416))=cfg_mode report "Runtime mode mismatch" severity failure;
            if board=0 then
              assert ttx>0 and ttx<=tdrain report "Invalid anchor return time" severity failure;
            end if;
            validated(board)<=observed;
          end if;
        elsif unsigned(status(board)(159 downto 128))>observed then
          observed:=to_integer(unsigned(status(board)(159 downto 128)));
          sample:=observed-1;
          log_addr(board)<=std_logic_vector(to_unsigned(sample mod 256,8));
          pending:=3;
        end if;
      end if;
    end process;
  end generate;
  process(clk)
    variable previous:a64:=(others=>(others=>'0'));
  begin
    if rising_edge(clk) then
      ticks<=ticks+1;
      if rst='0' and not invalid_test then
        for board in 0 to C_BOARDS-1 loop
          if unsigned(previous(board))>0 then
            assert unsigned(raw(board))=unsigned(previous(board))+1
              report "System raw measurement counter was altered" severity failure;
          end if;
          assert status(board)(36)='0'
            report "System error board="&integer'image(board)&" tick="&integer'image(ticks)&" status="&to_hstring(status(board)) severity failure;
        end loop;
      end if;
      previous:=raw;
    end if;
  end process;
  process
    variable complete:boolean;
    variable base,count:natural;
    type sizes_t is array(natural range <>) of positive;
    constant sizes:sizes_t:=(3,4,6,15,29,30,3);
  begin
    -- Reject an invalid configuration and suppress start, instead of wrapping IDs.
    invalid_test<=true;cfg_nodes<=0;
    wait for 128 ns;wait until falling_edge(clk);rst<='0';start(0)<='1';
    wait for 256 ns;
    for board in 0 to 2 loop
      assert status(board)(38)='1' and status(board)(32)='0' report "Invalid config accepted" severity failure;
    end loop;
    start<=(others=>'0');rst<='1';invalid_test<=false;
    for scenario in sizes'range loop
      if sizes(scenario)<=C_NODES and (not G_MAX_ONLY or sizes(scenario)=C_NODES) then
        for mode in 0 to 1 loop
          rst<='1';cfg_nodes<=sizes(scenario);cfg_mode<=mode*2;
          base:=0;
          for board in 0 to 2 loop
            count:=sizes(scenario)/3;
            if board<sizes(scenario) mod 3 then count:=count+1;end if;
            cfg_base(board)<=base;cfg_local(board)<=count;base:=base+count;
          end loop;
          wait for 128 ns;wait until falling_edge(clk);rst<='0';
          wait until falling_edge(clk);start(0)<='1';
          wait until falling_edge(clk);start(0)<='0';
          complete:=false;
          for timeout in 0 to 375000+G_RECORDS*7000 loop
            wait until rising_edge(clk);wait for 1 ns;
            complete:=true;
            for board in 0 to 2 loop
              if validated(board)<G_RECORDS then complete:=false;end if;
            end loop;
            exit when complete;
          end loop;
          assert complete report "Runtime campaign did not complete N="&integer'image(sizes(scenario))&" mode="&integer'image(mode*2) severity failure;
          -- The programmed register may change while running, but active
          -- configuration remains latched until the next reset.
          cfg_nodes<=0;cfg_mode<=1;
          wait for 128 ns;
          for board in 0 to 2 loop
            assert status(board)(38)='0' and unsigned(status(board)(223 downto 192))=sizes(scenario) and
              unsigned(status(board)(191 downto 160))=mode*2 report "Configuration changed without reset" severity failure;
          end loop;
          report "RUNTIME_PASS N="&integer'image(sizes(scenario))&" mode="&integer'image(mode*2) severity note;
          rst<='1';cfg_nodes<=sizes(scenario);cfg_mode<=mode*2;
          wait for 128 ns;
        end loop;
      end if;
    end loop;
    report "PASS tb_runtime_system" severity note;stop;wait;
  end process;
end architecture;
