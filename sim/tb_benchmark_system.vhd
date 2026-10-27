library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;
use work.benchmark_pkg.all;

-- Complete three-board portable system integration. This models digital
-- transport interfaces only; it does not claim proprietary Aurora-IP coverage.
entity tb_benchmark_system is
  generic(G_MODE:natural:=2; G_LOCAL_NODES:positive:=1;
          G_LATENCY:positive:=37; G_DATA_BYTES:positive:=6; G_RECORDS:positive:=12;
          G_ARM_DELAY:positive:=312500);
end entity;
architecture test of tb_benchmark_system is
  constant C_BOARDS:positive:=3;
  constant C_NODES:positive:=C_BOARDS*G_LOCAL_NODES;
  type a256 is array(0 to C_BOARDS-1) of std_logic_vector(255 downto 0);
  type a512 is array(0 to C_BOARDS-1) of std_logic_vector(511 downto 0);
  type a64 is array(0 to C_BOARDS-1) of std_logic_vector(63 downto 0);
  type a8 is array(0 to C_BOARDS-1) of std_logic_vector(7 downto 0);
  type counts_t is array(0 to C_BOARDS-1) of natural;
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
      generic map(G_MODE=>G_MODE,G_NODES=>C_NODES,G_NODE_BASE=>board*G_LOCAL_NODES,
        G_LOCAL_NODES=>G_LOCAL_NODES,G_DATA_BYTES=>G_DATA_BYTES,G_REF_BYTES=>2,
        G_PERIOD_CYCLES=>6250,G_ARM_DELAY_CYCLES=>G_ARM_DELAY,G_RUN_CYCLES=>G_RECORDS+2,G_FIFO_WORDS=>512,G_MAX_FRAME_BYTES=>4096,
        G_VLINK_LATENCY=>G_LATENCY,G_VLINK_FIFO_WORDS=>256)
      port map(clk_i=>clk,rst_i=>rst,start_i=>start(board),stop_i=>stop_run,links_up_i=>'1',link_fault_i=>'0',
        left_rx_data_i=>lr(board),left_rx_keep_i=>lrk(board),left_rx_valid_i=>lrv(board),left_rx_last_i=>lrl(board),
        left_tx_data_o=>ld(board),left_tx_keep_o=>lk(board),left_tx_valid_o=>lv(board),left_tx_last_o=>ll(board),left_tx_ready_i=>lready(board),
        right_rx_data_i=>rr(board),right_rx_keep_i=>rrk(board),right_rx_valid_i=>rrv(board),right_rx_last_i=>rrl(board),
        right_tx_data_o=>rd(board),right_tx_keep_o=>rk(board),right_tx_valid_o=>rv(board),right_tx_last_o=>rl(board),right_tx_ready_i=>rready(board),
        status_o=>status(board),raw_counter_o=>raw(board),log_addr_i=>log_addr(board),log_data_o=>logs(board));
    forward_link:entity work.virtual_neighbor_link
      generic map(G_LATENCY_CYCLES=>G_LATENCY,G_FIFO_WORDS=>256,G_CC_PHASE=>board*71+11)
      port map(clk,rst,rd(board),rk(board),rv(board),rl(board),rready(board),
        lr(NEXT_BOARD),lrk(NEXT_BOARD),lrv(NEXT_BOARD),lrl(NEXT_BOARD),open,open);
    reverse_link:entity work.virtual_neighbor_link
      generic map(G_LATENCY_CYCLES=>G_LATENCY,G_FIFO_WORDS=>256,G_CC_PHASE=>board*113+19)
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
            assert unsigned(logs(board)(415 downto 400))=C_NODES
              and unsigned(logs(board)(399 downto 384))=G_LOCAL_NODES
              and unsigned(logs(board)(383 downto 368))=board*G_LOCAL_NODES
              report "Journal segment metadata mismatch" severity failure;
            report "BENCH_CSV,"&integer'image(G_MODE)&","&integer'image(C_NODES)&","&integer'image(board)&","&integer'image(sample)&","&integer'image(to_integer(unsigned(logs(board)(95 downto 32))))&","&integer'image(to_integer(tuse))&","&integer'image(to_integer(tdrain))&","&integer'image(to_integer(ttx)) severity note;
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
      if rst='0' then
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
    variable complete:boolean:=false;
    variable tuse,tdrain,ttx:unsigned(63 downto 0);
  begin
    wait for 128 ns;wait until falling_edge(clk);rst<='0';
    wait until falling_edge(clk);start(0)<='1';
    wait until falling_edge(clk);start(0)<='0';
    -- Twelve records cross a maintenance round. The long campaign chooses
    -- 400 or 10000 while the reader extracts every record before BRAM wraps.
    for timeout in 0 to 375000+G_RECORDS*7000 loop
      wait until rising_edge(clk);wait for 1 ns;
      complete:=true;
      for board in 0 to C_BOARDS-1 loop
        if validated(board)<G_RECORDS then complete:=false;end if;
      end loop;
      exit when complete;
    end loop;
    assert complete report "System did not produce the requested completed journal records" severity failure;
    report "PASS tb_benchmark_system mode="&integer'image(G_MODE)&" N="&integer'image(C_NODES)&" latency="&integer'image(G_LATENCY)&" records="&integer'image(G_RECORDS) severity note;
    stop;wait;
  end process;
end architecture;
