library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;
use work.benchmark_pkg.all;

entity tb_rag_ring is
  generic(G_MODE:natural:=2;G_NODES:positive:=3;G_D:positive:=6;G_R:positive:=2;G_STALLS:boolean:=true;G_SKEW_CYCLES:natural:=0;G_CYCLES:positive:=1);
end;
architecture test of tb_rag_ring is
  signal clk:std_logic:='0';signal rst:std_logic:='1';
  signal start:std_logic_vector(G_NODES-1 downto 0):=(others=>'0');signal start_src:std_logic:='0';
  signal cyc:std_logic_vector(31 downto 0):=x"00000001";
  signal td:word_array_t(0 to G_NODES-1);signal tk:keep_array_t(0 to G_NODES-1);
  signal tv,tl,tr,rr,uv,dv,ev,ft,fr:std_logic_vector(0 to G_NODES-1):=(others=>'0');
  signal gate:std_logic_vector(0 to G_NODES-1):=(others=>'1');
  signal ce:u32_array_t(0 to G_NODES-1);signal hw:word_array_t(0 to G_NODES-1);
  signal addr:std_logic_vector(15 downto 0):=(others=>'0');signal db:byte_array_t(0 to G_NODES-1);
  signal count:natural:=0;
begin
  clk<=not clk after 8 ns;
  process(clk)begin if rising_edge(clk) then count<=count+1;end if;end process;
  nodes:for i in 0 to G_NODES-1 generate
    constant P:natural:=(i+G_NODES-1) mod G_NODES;
    constant NEXT_ID:natural:=(i+1) mod G_NODES;
  begin
    start(i)<=transport start_src after (i*G_SKEW_CYCLES)*16 ns;
    gate(i)<='0' when G_STALLS and ((count+3*i) mod 17=0 or (count+3*i) mod 17=1 or (count+3*i) mod 5000<6) else '1';
    tr(i)<=rr(NEXT_ID) and gate(i);
    dut:entity work.rag_node generic map(G_MODE=>G_MODE,G_NODES=>G_NODES,G_NODE_ID=>i,G_DATA_BYTES=>G_D,G_REF_BYTES=>G_R,G_FIFO_WORDS=>512,G_MAX_FRAME_BYTES=>4096)
    port map(clk_i=>clk,rst_i=>rst,start_i=>start(i),cycle_id_i=>cyc,
      rx_data_i=>td(P),rx_keep_i=>tk(P),rx_valid_i=>tv(P) and gate(P),rx_last_i=>tl(P),rx_ready_o=>rr(i),
      tx_data_o=>td(i),tx_keep_o=>tk(i),tx_valid_o=>tv(i),tx_last_o=>tl(i),tx_ready_i=>tr(i),
      useful_o=>uv(i),drained_o=>dv(i),error_o=>ev(i),crc_errors_o=>ce(i),fifo_highwater_o=>hw(i),first_tx_o=>ft(i),first_rx_o=>fr(i),data_addr_i=>addr,data_byte_o=>db(i));
    hold_check:process(clk)
      variable held:boolean:=false;variable old_d:std_logic_vector(15 downto 0);variable old_k:std_logic_vector(1 downto 0);variable old_l:std_logic;
    begin
      if rising_edge(clk) then
        if held and rst='0' then assert tv(i)='1' and td(i)=old_d and tk(i)=old_k and tl(i)=old_l report "TX changed during stall" severity failure;end if;
        held:=tv(i)='1' and tr(i)='0';old_d:=td(i);old_k:=tk(i);old_l:=tl(i);
      end if;
    end process;
  end generate;
  stimulus:process
    variable complete:boolean;
  begin
    wait for 64 ns;wait until falling_edge(clk);rst<='0';
    for cycle_num in 1 to G_CYCLES loop
    cyc<=std_logic_vector(to_unsigned(cycle_num,32));
    wait until falling_edge(clk);start_src<='1';
    wait until falling_edge(clk);start_src<='0';
    complete:=false;
    for timeout in 0 to 100000 loop
      wait until rising_edge(clk);wait for 1 ns;
      assert ev=(ev'range=>'0') report "RAG error flag" severity failure;
      if dv=(dv'range=>'1') then complete:=true;exit;end if;
    end loop;
    assert complete report "RAG failed to drain" severity failure;
    assert uv=(uv'range=>'1') report "Missing useful result" severity failure;
    for j in 0 to G_NODES*G_D-1 loop
      addr<=std_logic_vector(to_unsigned(j,16));wait for 1 ns;
      for i in 0 to G_NODES-1 loop
        if G_MODE=2 or i=0 then
          assert db(i)=data_pattern(j/G_D,cyc,j mod G_D) report "RAG table mismatch at node "&integer'image(i)&" byte "&integer'image(j) severity failure;
        end if;
      end loop;
    end loop;
    -- Keep a cycle identifier stable until all input and output are drained.
    for idle in 0 to G_NODES*G_SKEW_CYCLES+4 loop wait until falling_edge(clk);end loop;
    end loop;
    report "PASS tb_rag_ring mode="&integer'image(G_MODE)&" N="&integer'image(G_NODES)&" D="&integer'image(G_D)&" R="&integer'image(G_R)&" cycles="&integer'image(count) severity note;
    stop;wait;
  end process;
end architecture;
