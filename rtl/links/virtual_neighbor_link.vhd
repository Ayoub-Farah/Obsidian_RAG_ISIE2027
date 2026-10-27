library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
-- One independent unidirectional virtual Aurora link. No RX backpressure.
-- This is a configurable E1 transport model, not an analogue GTP emulator.
entity virtual_neighbor_link is
 generic(G_LATENCY_CYCLES:positive:=37; G_FIFO_WORDS:positive:=256;
         G_FRAME_GAP_CYCLES:natural:=2; G_CC_PERIOD:positive:=5000;
         G_CC_LENGTH:natural:=6; G_CC_PHASE:natural:=0);
 port(clk_i,rst_i:in std_logic;
      s_data_i:in std_logic_vector(15 downto 0);s_keep_i:in std_logic_vector(1 downto 0);
      s_valid_i,s_last_i:in std_logic;s_ready_o:out std_logic;
      m_data_o:out std_logic_vector(15 downto 0);m_keep_o:out std_logic_vector(1 downto 0);
      m_valid_o,m_last_o:out std_logic;
      empty_o:out std_logic;highwater_o:out std_logic_vector(15 downto 0));
end;
architecture rtl of virtual_neighbor_link is
 type words_t is array(0 to G_FIFO_WORDS-1) of std_logic_vector(18 downto 0);
 type times_t is array(0 to G_FIFO_WORDS-1) of unsigned(63 downto 0);
 signal words:words_t;signal due:times_t;
 signal rd,wr:natural range 0 to G_FIFO_WORDS-1:=0;
 signal count:natural range 0 to G_FIFO_WORDS:=0;
 signal highwater:natural range 0 to G_FIFO_WORDS:=0;
 signal raw:unsigned(63 downto 0):=(others=>'0');
 signal cc:natural range 0 to G_CC_PERIOD-1:=G_CC_PHASE mod G_CC_PERIOD;
 signal gap:natural range 0 to G_FRAME_GAP_CYCLES:=0;
 signal take_in,take_out,cc_active:std_logic;
 function next_ptr(p:natural) return natural is
 begin if p=G_FIFO_WORDS-1 then return 0;else return p+1;end if;end;
 begin
 assert G_FIFO_WORDS<=65535 severity failure;
 assert G_CC_LENGTH<G_CC_PERIOD severity failure;
 cc_active<='1' when cc<G_CC_LENGTH else '0';
 s_ready_o<='1' when count<G_FIFO_WORDS and gap=0 and cc_active='0' else '0';
 take_in<=s_valid_i and s_ready_o;
 m_valid_o<='1' when count>0 and due(rd)<=raw else '0';
 take_out<=m_valid_o;
 m_data_o<=words(rd)(15 downto 0);m_keep_o<=words(rd)(17 downto 16);m_last_o<=words(rd)(18);
 empty_o<='1' when count=0 else '0';highwater_o<=std_logic_vector(to_unsigned(highwater,16));
 process(clk_i)
 variable c:natural range 0 to G_FIFO_WORDS;
 begin if rising_edge(clk_i) then
 if rst_i='1' then rd<=0;wr<=0;count<=0;highwater<=0;raw<=(others=>'0');gap<=0;cc<=G_CC_PHASE mod G_CC_PERIOD;
 else
 raw<=raw+1;if cc=G_CC_PERIOD-1 then cc<=0;else cc<=cc+1;end if;
 if gap>0 and cc_active='0' then gap<=gap-1;end if;
 c:=count;
 if take_out='1' then rd<=next_ptr(rd);c:=c-1;end if;
 if take_in='1' then
 words(wr)<=s_last_i&s_keep_i&s_data_i;due(wr)<=raw+G_LATENCY_CYCLES;
 wr<=next_ptr(wr);c:=c+1;if s_last_i='1' then gap<=G_FRAME_GAP_CYCLES;end if;
 end if;
 count<=c;if c>highwater then highwater<=c;end if;
 end if;end if;end process;
end;
