library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
-- Capture every physical RX valid word. Aurora has no RX tready.
entity aurora_rx_capture is
 generic(G_WORDS:positive:=2048);
 port(clk_i,rst_i:in std_logic;
 rx_data_i:in std_logic_vector(15 downto 0);rx_keep_i:in std_logic_vector(1 downto 0);rx_valid_i,rx_last_i:in std_logic;
 data_o:out std_logic_vector(15 downto 0);keep_o:out std_logic_vector(1 downto 0);valid_o,last_o:out std_logic;ready_i:in std_logic;
 empty_o,overflow_o:out std_logic;highwater_o:out std_logic_vector(15 downto 0));
end;
architecture rtl of aurora_rx_capture is
 type mem_t is array(0 to G_WORDS-1) of std_logic_vector(18 downto 0);
 signal mem:mem_t;signal rd,wr:natural range 0 to G_WORDS-1:=0;
 signal count,hw:natural range 0 to G_WORDS:=0;signal overflow:std_logic:='0';
 function inc(p:natural) return natural is begin if p=G_WORDS-1 then return 0;else return p+1;end if;end;
 begin
 assert G_WORDS<65536 severity failure;
 data_o<=mem(rd)(15 downto 0);keep_o<=mem(rd)(17 downto 16);last_o<=mem(rd)(18);
 valid_o<='1' when count>0 else '0';empty_o<='1' when count=0 else '0';
 overflow_o<=overflow;highwater_o<=std_logic_vector(to_unsigned(hw,16));
 process(clk_i) variable c:natural range 0 to G_WORDS;begin
 if rising_edge(clk_i) then
 if rst_i='1' then rd<=0;wr<=0;count<=0;hw<=0;overflow<='0';
 else c:=count;
 if count>0 and ready_i='1' then rd<=inc(rd);c:=c-1;end if;
 if rx_valid_i='1' then
 if c<G_WORDS then mem(wr)<=rx_last_i&rx_keep_i&rx_data_i;wr<=inc(wr);c:=c+1;else overflow<='1';end if;
 end if;count<=c;if c>hw then hw<=c;end if;
 end if;end if;end process;
end;
