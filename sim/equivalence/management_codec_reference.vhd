library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.benchmark_pkg.all;

-- Bounded management frames. RX has no backpressure, exactly like Aurora.
-- Timestamps are captured at the FIRST valid RX / accepted TX word.
entity management_codec_reference is
 generic(G_NODE_ID:natural:=0; G_NODES:positive:=3; G_MODE:natural:=2; G_PERIOD_CYCLES:positive:=6250;G_LEFT_INPUT:boolean:=true);
 port(clk_i,rst_i:in std_logic; time_i:in std_logic_vector(63 downto 0);
 request_i:in std_logic; kind_i:in std_logic_vector(7 downto 0); sequence_i:in std_logic_vector(31 downto 0); timestamp_i:in std_logic_vector(63 downto 0);
 ready_o,done_o:out std_logic; tx_stamp_o:out std_logic_vector(63 downto 0);
 tx_data_o:out std_logic_vector(15 downto 0);tx_keep_o:out std_logic_vector(1 downto 0);tx_valid_o,tx_last_o:out std_logic;tx_ready_i:in std_logic;
 rx_data_i:in std_logic_vector(15 downto 0);rx_keep_i:in std_logic_vector(1 downto 0);rx_valid_i,rx_last_i:in std_logic;
 event_o:out std_logic;rx_kind_o:out std_logic_vector(7 downto 0);rx_sequence_o:out std_logic_vector(31 downto 0);rx_timestamp_o,rx_stamp_o:out std_logic_vector(63 downto 0);error_o:out std_logic);
end;
architecture rtl of management_codec_reference is
 signal txmem:byte_array_t(0 to 43):=(others=>(others=>'0'));
 signal rxmem:byte_array_t(0 to 43):=(others=>(others=>'0'));
 signal busy:std_logic:='0';signal txindex:natural range 0 to 43:=0;signal txlength:natural range 0 to 44:=36;
 signal ignoring_data:std_logic:='0';
 signal rxindex:natural range 0 to 44:=0;signal rxfirst:std_logic_vector(63 downto 0):=(others=>'0');signal badframe:std_logic:='0';
begin
 ready_o<=not busy;tx_valid_o<=busy;tx_keep_o<="11";
 tx_data_o<=txmem(txindex)&txmem(txindex+1) when busy='1' else (others=>'0');
 tx_last_o<='1' when busy='1' and txindex+2=txlength else '0';
 process(clk_i)
 variable m:byte_array_t(0 to 43);variable h:byte_array_t(0 to 15);variable len,pl,n,origin:natural;
 variable c16:std_logic_vector(15 downto 0);variable c32:std_logic_vector(31 downto 0);variable bad:std_logic;variable first:std_logic_vector(63 downto 0);
 begin if rising_edge(clk_i) then
 done_o<='0';event_o<='0';error_o<='0';
 if rst_i='1' then busy<='0';txindex<=0;rxindex<=0;badframe<='0';ignoring_data<='0';tx_stamp_o<=(others=>'0');
 else
 if busy='0' and request_i='1' then
 m:=(others=>(others=>'0'));pl:=16;if kind_i=x"20" then pl:=24;end if;len:=20+pl;
 origin:=G_NODE_ID;if kind_i=x"20" then origin:=0;end if;
h:=make_header(to_integer(unsigned(kind_i)),origin,G_NODES,pl,(others=>'0'));
 for j in 0 to 15 loop m(j):=h(j);end loop;
 for j in 0 to 3 loop m(16+j):=sequence_i(31-j*8 downto 24-j*8);end loop;
 if kind_i=x"20" then
 m(20):=std_logic_vector(to_unsigned(G_MODE,8));
 for j in 0 to 7 loop m(24+j):=timestamp_i(63-j*8 downto 56-j*8);end loop;
 m(36):=std_logic_vector(to_unsigned((G_PERIOD_CYCLES/16777216)mod 256,8));m(37):=std_logic_vector(to_unsigned((G_PERIOD_CYCLES/65536)mod 256,8));m(38):=std_logic_vector(to_unsigned((G_PERIOD_CYCLES/256)mod 256,8));m(39):=std_logic_vector(to_unsigned(G_PERIOD_CYCLES mod 256,8));
 elsif kind_i=x"21" then
 -- READY describes the contiguous prepared suffix.
 m(20):=std_logic_vector(to_unsigned((G_NODES-G_NODE_ID)/256,8));m(21):=std_logic_vector(to_unsigned((G_NODES-G_NODE_ID)mod 256,8));
 else for j in 0 to 7 loop m(20+j):=timestamp_i(63-j*8 downto 56-j*8);end loop;
 end if;
 c32:=x"FFFFFFFF";for j in 0 to 39 loop if j<len-4 then c32:=crc32_byte(c32,m(j));end if;end loop;c32:=not c32;
 for j in 0 to 3 loop m(len-4+j):=c32(8*j+7 downto 8*j);end loop;
 txmem<=m;txlength<=len;txindex<=0;busy<='1';
 elsif busy='1' and tx_ready_i='1' then
 if txindex=0 then tx_stamp_o<=time_i;end if;
 if txindex+2=txlength then busy<='0';done_o<='1';txindex<=0;else txindex<=txindex+2;end if;
 end if;
 if rx_valid_i='1' then
 if ignoring_data='1' then
 if rx_last_i='1' then rxindex<=0;badframe<='0';ignoring_data<='0';end if;
 else
 m:=rxmem;n:=rxindex;bad:=badframe;first:=rxfirst;if n=0 then first:=time_i;rxfirst<=time_i;end if;
 if rx_keep_i/="11" then bad:='1';end if;
 if n<44 then m(n):=rx_data_i(15 downto 8);n:=n+1;else bad:='1';end if;
 if n<44 then m(n):=rx_data_i(7 downto 0);n:=n+1;else bad:='1';end if;
 if n>=4 and unsigned(m(3))>=1 and unsigned(m(3))<=5 then
 if rx_last_i='1' then rxindex<=0;ignoring_data<='0';badframe<='0';else ignoring_data<='1';rxindex<=n;end if;
 elsif rx_last_i='1' then
 if n/=36 and n/=44 then bad:='1';end if;
 if m(0)/=x"C3" or m(1)/=x"5A" or m(2)/=x"01" or to_integer(unsigned(std_logic_vector'(m(6)&m(7))))/=G_NODES then bad:='1';end if;
 c16:=x"FFFF";for j in 0 to 13 loop c16:=crc16_byte(c16,m(j));end loop;if c16/=m(14)&m(15) then bad:='1';end if;
 c32:=x"FFFFFFFF";for j in 0 to 39 loop if j<n-4 then c32:=crc32_byte(c32,m(j));end if;end loop;c32:=not c32;
 if n>=4 then for j in 0 to 3 loop if m(n-4+j)/=c32(8*j+7 downto 8*j) then bad:='1';end if;end loop;end if;
 if to_integer(unsigned(std_logic_vector'(m(12)&m(13))))+20/=n then bad:='1';end if;
 origin:=to_integer(unsigned(std_logic_vector'(m(4)&m(5))));
 if m(3)=x"20" then
 if origin/=0 then bad:='1';end if;
 elsif G_LEFT_INPUT then
 if G_NODE_ID=0 or origin/=G_NODE_ID-1 then bad:='1';end if;
 else
 if G_NODE_ID=G_NODES-1 or origin/=G_NODE_ID+1 then bad:='1';end if;
 end if;
 if m(3)=x"20" then
 if n/=44 or to_integer(unsigned(m(20)))/=G_MODE or unsigned(std_logic_vector'(m(36)&m(37)&m(38)&m(39)))/=to_unsigned(G_PERIOD_CYCLES,32) then bad:='1';end if;
 end if;
 if bad='0' and ((unsigned(m(3))>=16 and unsigned(m(3))<=20) or m(3)=x"20" or m(3)=x"21") then
 event_o<='1';rx_kind_o<=m(3);rx_sequence_o<=m(16)&m(17)&m(18)&m(19);rx_stamp_o<=first;
 if m(3)=x"20" then rx_timestamp_o<=m(24)&m(25)&m(26)&m(27)&m(28)&m(29)&m(30)&m(31);
 else rx_timestamp_o<=m(20)&m(21)&m(22)&m(23)&m(24)&m(25)&m(26)&m(27);end if;
 else error_o<='1';end if;
 rxindex<=0;badframe<='0';
 else rxmem<=m;rxindex<=n;badframe<=bad;end if;
 end if;end if;
 end if;end if;end process;
end;
