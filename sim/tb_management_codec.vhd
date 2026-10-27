library ieee;use ieee.std_logic_1164.all;use ieee.numeric_std.all;use work.benchmark_pkg.all;use std.env.all;
entity tb_management_codec is end;
architecture test of tb_management_codec is
 signal clk:std_logic:='0';signal rst:std_logic:='1';signal tick:unsigned(63 downto 0):=(others=>'0');signal tm:std_logic_vector(63 downto 0);
 signal req,ready,done,tv,tl,tr,event,err:std_logic:='0';signal kind,rxkind:std_logic_vector(7 downto 0):=x"10";signal td,manual_data,rxdata:std_logic_vector(15 downto 0);signal tk:std_logic_vector(1 downto 0);signal seq:std_logic_vector(31 downto 0);signal ts,stamp,txstamp:std_logic_vector(63 downto 0);
 signal rxvalid,rxlast:std_logic;signal manual,manual_valid,manual_last,corrupt:std_logic:='0';signal word_index:natural:=0;signal events,errors:natural:=0;
begin clk<=not clk after 8 ns;tm<=std_logic_vector(shift_left(tick,16));tr<='0' when tick mod 7=0 else '1';
 process(clk)begin if rising_edge(clk)then tick<=tick+1;end if;end process;
 tx:entity work.management_codec generic map(0,3,2,6250)port map(clk,rst,tm,req,kind,x"11223344",x"0000000012345678",ready,done,txstamp,td,tk,tv,tl,tr,(others=>'0'),"11",'0','0',open,open,open,open,open,open);
 rxdata<=manual_data when manual='1' else td xor x"0001" when corrupt='1' and word_index=10 else td;
 rxvalid<=manual_valid when manual='1' else tv and tr;rxlast<=manual_last when manual='1' else tl;
 rx:entity work.management_codec generic map(1,3,2,6250)port map(clk,rst,tm,'0',x"00",x"00000000",(others=>'0'),open,open,open,open,open,open,open,'1',rxdata,"11",rxvalid,rxlast,event,rxkind,seq,ts,stamp,err);
 process(clk)variable held:boolean:=false;variable saved:std_logic_vector(18 downto 0);begin if rising_edge(clk)then
 if event='1' then events<=events+1;assert rxkind=x"10" and seq=x"11223344" and ts=x"0000000012345678" report "Decoded management contents differ" severity failure;end if;
 if err='1' then errors<=errors+1;end if;
 if held then assert tv='1' and (td&tk&tl)=saved report "TX changed while stalled" severity failure;end if;
 held:=tv='1' and tr='0';saved:=td&tk&tl;
 if tv='1' and tr='1' then if tl='1' then word_index<=0;else word_index<=word_index+1;end if;end if;
 end if;end process;
 process variable h:byte_array_t(0 to 15);variable b0,b1:byte_t;
 procedure send_management(k:std_logic_vector(7 downto 0)) is begin
 wait until falling_edge(clk);kind<=k;req<='1';wait until falling_edge(clk);req<='0';wait until done='1';wait until falling_edge(clk);for j in 0 to 4 loop wait until falling_edge(clk);end loop;end;
 begin wait for 100 ns;wait until falling_edge(clk);rst<='0';manual<='1';h:=make_header(1,0,3,60,x"00000007");
 for w in 0 to 39 loop
 if w<8 then b0:=h(2*w);b1:=h(2*w+1);else b0:=x"AA";b1:=x"55";end if;
 manual_data<=b0&b1;manual_valid<='1';if w=39 then manual_last<='1';else manual_last<='0';end if;wait until falling_edge(clk);manual_valid<='0';if w mod 3=0 then wait until falling_edge(clk);end if;
 end loop;manual_last<='0';wait until falling_edge(clk);assert events=0 and errors=0 report "Long DATA frame was mistaken for management" severity failure;
 manual<='0';send_management(x"15");assert errors=1 and events=0 report "Unsupported management type not rejected" severity failure;
 send_management(x"10");assert events=1 and errors=1 report "Management frame after DATA was lost" severity failure;
 corrupt<='1';send_management(x"10");corrupt<='0';assert errors=2 and events=1 report "Bad CRC management frame accepted" severity failure;
 send_management(x"10");assert errors=2 and events=2 report "Parser did not recover after bad frame" severity failure;
 report "PASS management codec: long DATA ignored, management retained, unknown/CRC errors, TX stalls" severity note;stop;
 end process;
end;
