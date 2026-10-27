library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;
use work.benchmark_pkg.all;

-- The master's own reference is known locally. Its useful event must depend
-- on the DATA bitmap, while REFERENCES return remains a drain prerequisite.
entity tb_rag_c_useful is end;
architecture test of tb_rag_c_useful is
  constant C_N:positive:=3;constant C_D:positive:=6;constant C_R:positive:=32;
  signal clk:std_logic:='0';signal rst:std_logic:='1';signal start:std_logic:='0';
  signal rd,td:std_logic_vector(15 downto 0):=(others=>'0');signal rk,tk:std_logic_vector(1 downto 0):="11";
  signal rv,rl,rr,tv,tl,uv,dv,ev,ft,fr:std_logic:='0';
  signal ce:std_logic_vector(31 downto 0);signal hw:std_logic_vector(15 downto 0);signal db:byte_t;
  signal addr:std_logic_vector(15 downto 0):=(others=>'0');signal tx_finished:std_logic:='0';
begin
  clk<=not clk after 8 ns;
  dut:entity work.rag_node generic map(G_MODE=>0,G_NODES=>C_N,G_NODE_ID=>0,G_DATA_BYTES=>C_D,G_REF_BYTES=>C_R,G_FIFO_WORDS=>256)
    port map(clk_i=>clk,rst_i=>rst,start_i=>start,cycle_id_i=>x"00000001",rx_data_i=>rd,rx_keep_i=>rk,rx_valid_i=>rv,rx_last_i=>rl,rx_ready_o=>rr,
      tx_data_o=>td,tx_keep_o=>tk,tx_valid_o=>tv,tx_last_o=>tl,tx_ready_i=>'1',useful_o=>uv,drained_o=>dv,error_o=>ev,crc_errors_o=>ce,fifo_highwater_o=>hw,first_tx_o=>ft,first_rx_o=>fr,data_addr_i=>addr,data_byte_o=>db);
  process(clk)begin if rising_edge(clk) and tv='1' and tl='1' then tx_finished<='1';end if;end process;
  stimulus:process
    variable useful_time:time;variable refs_return_time:time;
    procedure transmit(kind,origin,plen:natural) is
      variable f:byte_array_t(0 to 19+plen);variable h:byte_array_t(0 to 15);
      variable c:std_logic_vector(31 downto 0);
    begin
      h:=make_header(kind,origin,C_N,plen,x"00000001");
      for j in 0 to 15 loop f(j):=h(j);end loop;
      for j in 0 to plen-1 loop
        if kind=1 then f(16+j):=data_pattern(origin,x"00000001",j);
        else f(16+j):=ref_pattern(j/C_R,x"00000001",j mod C_R);end if;
      end loop;
      c:=x"FFFFFFFF";for j in 0 to 15+plen loop c:=crc32_byte(c,f(j));end loop;c:=not c;
      for j in 0 to 3 loop f(16+plen+j):=c(8*j+7 downto 8*j);end loop;
      for w in 0 to (f'length+1)/2-1 loop
        wait until falling_edge(clk);rd(15 downto 8)<=f(2*w);rk<="11";rl<='0';
        if 2*w+1<f'length then rd(7 downto 0)<=f(2*w+1);else rd(7 downto 0)<=x"00";rk<="10";end if;
        if w=(f'length+1)/2-1 then rl<='1';end if;
        rv<='1';loop wait until rising_edge(clk);exit when rr='1';end loop;
      end loop;
      wait until falling_edge(clk);rv<='0';rl<='0';
    end procedure;
  begin
    wait for 64 ns;wait until falling_edge(clk);rst<='0';wait until falling_edge(clk);start<='1';wait until falling_edge(clk);start<='0';
    transmit(1,1,C_D);transmit(1,2,C_D);
    wait for 1 ns;
    assert ev='0' and uv='1' report "RAG_C master waited for REFERENCES return despite complete DATA bitmap" severity failure;
    assert dv='0' report "RAG_C drained before REFERENCES return" severity failure;
    useful_time:=now;
    -- Every DATA byte, including the local node's data, is already valid.
    for j in 0 to C_N*C_D-1 loop
      addr<=std_logic_vector(to_unsigned(j,16));wait for 1 ns;
      assert db=data_pattern(j/C_D,x"00000001",j mod C_D) report "RAG_C master table mismatch" severity failure;
    end loop;
    if tx_finished/='1' then wait until tx_finished='1';end if;
    assert uv='1' and dv='0' report "Useful/drain distinction lost before reference return" severity failure;
    transmit(2,0,C_N*C_R);refs_return_time:=now;
    for timeout in 0 to 1000 loop wait until rising_edge(clk);exit when dv='1';end loop;
    assert ev='0' and uv='1' and dv='1' and useful_time<refs_return_time report "RAG_C final drain/reference ordering incorrect" severity failure;
    report "PASS tb_rag_c_useful: master DATA availability precedes REFERENCES return; protocol drain still waits" severity note;stop;wait;
  end process;
end;
