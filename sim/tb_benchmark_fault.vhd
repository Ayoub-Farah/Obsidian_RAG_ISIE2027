library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;
use work.benchmark_pkg.all;
entity tb_benchmark_fault is generic(G_KIND:natural:=0);end;
architecture test of tb_benchmark_fault is
  type a256_t is array(0 to 2) of std_logic_vector(255 downto 0);
  type a512_t is array(0 to 2) of std_logic_vector(511 downto 0);
  type a64_t is array(0 to 2) of std_logic_vector(63 downto 0);
  function fifo_words return positive is begin if G_KIND=2 then return 8;else return 256;end if;end;
  signal clk:std_logic:='0';signal rst:std_logic:='1';signal start:std_logic_vector(0 to 2):=(others=>'0');
  signal fault:std_logic_vector(0 to 2):=(others=>'0');signal up:std_logic_vector(0 to 2):=(others=>'1');
  signal ld,rd,lr,rr:word_array_t(0 to 2);signal lk,rk,lrk,rrk:keep_array_t(0 to 2);
  signal lv,rv,ll,rl,lready,rready,lrv,rrv,lrl,rrl:std_logic_vector(0 to 2);
  signal status:a256_t;signal logs:a512_t;signal raw:a64_t;
begin
  clk<=not clk after 8 ns;
  boards:for i in 0 to 2 generate
    constant P:natural:=(i+2) mod 3;constant N:natural:=(i+1) mod 3;
  begin
    dut:entity work.benchmark_system generic map(G_MODE=>2,G_NODES=>3,G_NODE_BASE=>i,G_LOCAL_NODES=>1,G_DATA_BYTES=>128,G_FIFO_WORDS=>fifo_words,G_ARM_DELAY_CYCLES=>10000)
      port map(clk_i=>clk,rst_i=>rst,start_i=>start(i),stop_i=>'0',links_up_i=>up(i),link_fault_i=>fault(i),
        left_rx_data_i=>lr(i),left_rx_keep_i=>lrk(i),left_rx_valid_i=>lrv(i),left_rx_last_i=>lrl(i),left_tx_data_o=>ld(i),left_tx_keep_o=>lk(i),left_tx_valid_o=>lv(i),left_tx_last_o=>ll(i),left_tx_ready_i=>lready(i),
        right_rx_data_i=>rr(i),right_rx_keep_i=>rrk(i),right_rx_valid_i=>rrv(i),right_rx_last_i=>rrl(i),right_tx_data_o=>rd(i),right_tx_keep_o=>rk(i),right_tx_valid_o=>rv(i),right_tx_last_o=>rl(i),right_tx_ready_i=>rready(i),
        status_o=>status(i),raw_counter_o=>raw(i),log_addr_i=>x"00",log_data_o=>logs(i));
    fwd:entity work.virtual_neighbor_link generic map(G_LATENCY_CYCLES=>37,G_FIFO_WORDS=>256,G_CC_PHASE=>i*71+11)
      port map(clk,rst,rd(i),rk(i),rv(i),rl(i),rready(i),lr(N),lrk(N),lrv(N),lrl(N),open,open);
    rev:entity work.virtual_neighbor_link generic map(G_LATENCY_CYCLES=>37,G_FIFO_WORDS=>256,G_CC_PHASE=>i*113+19)
      port map(clk,rst,ld(i),lk(i),lv(i),ll(i),lready(i),rr(P),rrk(P),rrv(P),rrl(P),open,open);
  end generate;
  raw_is_monotonic:process(clk)
    variable previous:a64_t:=(others=>(others=>'0'));
  begin
    if rising_edge(clk) then
      if rst='0' then for i in 0 to 2 loop
        if unsigned(previous(i))>0 then assert unsigned(raw(i))=unsigned(previous(i))+1 report "Link fault reset raw measurement time" severity failure;end if;
      end loop;end if;
      previous:=raw;
    end if;
  end process;
  stimulus:process
    variable launched,recorded:boolean:=false;
  begin
    wait for 128 ns;wait until falling_edge(clk);rst<='0';wait until falling_edge(clk);start(0)<='1';wait until falling_edge(clk);start(0)<='0';
    for timeout in 0 to 500000 loop
      wait until rising_edge(clk);
      if status(1)(32)='1' and rv(1)='1' and rready(1)='1' then launched:=true;exit;end if;
    end loop;
    assert launched report "Fault test did not reach first DATA transmission" severity failure;
    -- Trigger well inside the long 128-byte DATA frame, after its header starts.
    for k in 0 to 5 loop wait until rising_edge(clk);end loop;
    wait until falling_edge(clk);
    if G_KIND=0 then fault(1)<='1';elsif G_KIND=1 then up(1)<='0';end if;
    for k in 0 to 15 loop wait until falling_edge(clk);end loop;
    fault(1)<='0';up(1)<='1';
    for timeout in 0 to 10000 loop
      wait until rising_edge(clk);
      if unsigned(status(1)(159 downto 128))>0 then recorded:=true;exit;end if;
    end loop;
    assert recorded report "Faulted period disappeared from journal" severity failure;
    for k in 0 to 4 loop wait until rising_edge(clk);end loop;
    assert status(1)(36)='1' and status(1)(34)='0' report "Faulted transaction reported useful success" severity failure;
    assert logs(1)(320)='1' report "Faulted journal lacks error flag" severity failure;
    if G_KIND=2 then assert logs(1)(327)='1' report "Tiny FIFO loss not flagged as transport overflow" severity failure;
    else assert logs(1)(326)='1' report "Faulted journal lacks channel-reset flag" severity failure;end if;
    assert logs(1)(223 downto 160)=(63 downto 0=>'1') report "Faulted incomplete protocol received a valid drained time" severity failure;
    report "PASS tb_benchmark_fault kind="&integer'image(G_KIND)&": in-frame link reset is journaled, cannot succeed, raw time stays monotonic" severity note;stop;wait;
  end process;
end;
