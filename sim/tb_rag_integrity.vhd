library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;
use work.benchmark_pkg.all;
entity tb_rag_integrity is
  -- 0 valid/CT; 1 corrupt payload; 2 corrupt header; 3 stale; 4 duplicate.
  generic(G_FAULT:natural:=0);
end;
architecture test of tb_rag_integrity is
  constant C_N:positive:=3;constant C_D:positive:=7;constant C_R:positive:=33;
  constant C_P:natural:=C_N*C_R;constant C_BYTES:natural:=20+C_P;
  signal clk:std_logic:='0';signal rst:std_logic:='1';signal start:std_logic:='0';
  signal rd,td:std_logic_vector(15 downto 0):=(others=>'0');signal rk,tk:std_logic_vector(1 downto 0):="11";
  signal rv,rl,rr,tv,tl,tr,uv,dv,ev,ft,fr:std_logic:='0';
  signal ce:std_logic_vector(31 downto 0);signal hw:std_logic_vector(15 downto 0);signal db:byte_t;
  signal rx_complete,relay_started:std_logic:='0';signal txframes:natural:=0;
  signal count:natural:=0;signal expected_frame:byte_array_t(0 to C_BYTES-1);
begin
  clk<=not clk after 8 ns;
  tr<='0' when count mod 13=4 or count mod 13=5 else '1';
  dut:entity work.rag_node generic map(G_MODE=>0,G_NODES=>C_N,G_NODE_ID=>1,G_DATA_BYTES=>C_D,G_REF_BYTES=>C_R,G_FIFO_WORDS=>64)
    port map(clk_i=>clk,rst_i=>rst,start_i=>start,cycle_id_i=>x"00000001",rx_data_i=>rd,rx_keep_i=>rk,rx_valid_i=>rv,rx_last_i=>rl,rx_ready_o=>rr,
      tx_data_o=>td,tx_keep_o=>tk,tx_valid_o=>tv,tx_last_o=>tl,tx_ready_i=>tr,useful_o=>uv,drained_o=>dv,error_o=>ev,crc_errors_o=>ce,fifo_highwater_o=>hw,first_tx_o=>ft,first_rx_o=>fr,data_addr_i=>x"0000",data_byte_o=>db);
  process(clk)
    variable in_frame:boolean:=false;variable output_byte:natural:=0;variable incoming_seen:boolean:=false;variable incoming_first:natural:=0;
  begin
    if rising_edge(clk) then
      count<=count+1;
      if rv='1' and rr='1' and not incoming_seen then incoming_seen:=true;incoming_first:=count;end if;
      if tv='1' and tr='1' then
        if not in_frame and txframes=1 then
          relay_started<='1';assert count-incoming_first>=10 report "Header routing delay was below10 cycles" severity failure;
          if G_FAULT=0 or G_FAULT=1 then assert rx_complete='0' report "Relay waited for full CRC32: not CT" severity failure;end if;
        end if;
        if txframes>=1 then
          assert td(15 downto 8)=expected_frame(output_byte) report "Relay changed first byte" severity failure;
          if output_byte+1<C_BYTES then assert td(7 downto 0)=expected_frame(output_byte+1) report "Relay changed second byte" severity failure;end if;
          if tl='1' then output_byte:=0;else output_byte:=output_byte+2;end if;
        end if;
        in_frame:=true;
        if tl='1' then txframes<=txframes+1;in_frame:=false;end if;
      end if;
    end if;
  end process;
  stimulus:process
    variable f:byte_array_t(0 to C_BYTES-1);variable h:byte_array_t(0 to 15);
    variable c:std_logic_vector(31 downto 0);variable cy:std_logic_vector(31 downto 0);
    procedure transmit is
    begin
      for w in 0 to (C_BYTES+1)/2-1 loop
        wait until falling_edge(clk);
        -- Pauses in VALID are allowed inside the same frame.
        if w mod 7=3 then rv<='0';wait until falling_edge(clk);end if;
        rd(15 downto 8)<=f(2*w);rk<="11";rl<='0';
        if 2*w+1<C_BYTES then rd(7 downto 0)<=f(2*w+1);else rd(7 downto 0)<=x"EE";rk<="10";end if;
        if w=(C_BYTES+1)/2-1 then rl<='1';end if;
        rv<='1';
        loop wait until rising_edge(clk);exit when rr='1';end loop;
      end loop;
      wait until falling_edge(clk);rv<='0';rl<='0';rx_complete<='1';
    end procedure;
  begin
    wait for 64 ns;wait until falling_edge(clk);rst<='0';wait until falling_edge(clk);start<='1';wait until falling_edge(clk);start<='0';
    wait until txframes=1;wait until falling_edge(clk);
    cy:=x"00000001";if G_FAULT=3 then cy:=x"00000000";end if;
    h:=make_header(2,0,C_N,C_P,cy);
    for j in 0 to 15 loop f(j):=h(j);end loop;
    for j in 0 to C_P-1 loop f(16+j):=ref_pattern(j/C_R,cy,j mod C_R);end loop;
    c:=x"FFFFFFFF";for j in 0 to C_P+15 loop c:=crc32_byte(c,f(j));end loop;c:=not c;
    for j in 0 to 3 loop f(16+C_P+j):=c(8*j+7 downto 8*j);end loop;
    if G_FAULT=1 then f(30):=f(30) xor x"01";end if;
    if G_FAULT=2 then f(4):=f(4) xor x"01";end if;
    expected_frame<=f;
    transmit;
    if G_FAULT=4 then
      for k in 0 to 30 loop wait until rising_edge(clk);end loop;
      transmit;
    end if;
    for timeout in 0 to 1000 loop wait until rising_edge(clk);end loop;
    if G_FAULT=0 then
      assert uv='1' and dv='1' and ev='0' and ce=x"00000000" and relay_started='1' and txframes=2 report "Valid CT frame rejected" severity failure;
    else
      assert ev='1' and uv='0' and dv='0' report "Invalid cycle reported successful" severity failure;
      if G_FAULT=1 then assert ce=x"00000001" and txframes=2 report "CRC error did not propagate" severity failure;end if;
      if G_FAULT=2 or G_FAULT=3 then assert txframes=1 report "Invalid header/stale cycle relayed" severity failure;end if;
    end if;
    report "PASS tb_rag_integrity fault="&integer'image(G_FAULT) severity note;stop;wait;
  end process;
end;
