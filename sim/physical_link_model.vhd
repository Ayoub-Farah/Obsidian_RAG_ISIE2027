-- Simulation-only physical transport abstraction, not an Aurora-IP model.
-- Separate endpoint clocks, finite storage, propagation and CC-like TX pauses.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity physical_link_model is
  generic(G_DELAY:time:=592 ns;G_PHASE:natural:=0;G_DEPTH:positive:=8192;G_GAPS:boolean:=false);
  port(tx_clk_i,rx_clk_i,rst_i:in std_logic;
    data_i:in std_logic_vector(15 downto 0);keep_i:in std_logic_vector(1 downto 0);
    valid_i,last_i:in std_logic;ready_o:out std_logic;
    data_o:out std_logic_vector(15 downto 0);keep_o:out std_logic_vector(1 downto 0);valid_o,last_o:out std_logic);
end;
architecture model of physical_link_model is
  type mem_t is array(0 to G_DEPTH-1) of std_logic_vector(18 downto 0);
  type times_t is array(0 to G_DEPTH-1) of time;
  signal mem:mem_t;signal due:times_t;
  signal wr,rd:natural:=0;signal phase:natural:=G_PHASE;signal rxphase:natural:=0;signal ready:std_logic;
begin
  ready<='1' when (phase mod 5000)>=6 and wr-rd<G_DEPTH and (not G_GAPS or (phase mod 37)>=7) else '0';ready_o<=ready;
  process(tx_clk_i) begin if rising_edge(tx_clk_i) then
    if rst_i='1' then wr<=0;phase<=G_PHASE;
    else phase<=phase+1;
      if valid_i='1' and ready='1' then
        mem(wr mod G_DEPTH)<=last_i & keep_i & data_i;due(wr mod G_DEPTH)<=now+G_DELAY;wr<=wr+1;
      end if;
    end if;
  end if;end process;
  process(rx_clk_i) begin if rising_edge(rx_clk_i) then
    valid_o<='0';rxphase<=rxphase+1;
    if rst_i='1' then rd<=0;rxphase<=0;
    elsif rd<wr and (not G_GAPS or (rxphase mod 19)/=0) then
      if now>=due(rd mod G_DEPTH) then
        data_o<=mem(rd mod G_DEPTH)(15 downto 0);keep_o<=mem(rd mod G_DEPTH)(17 downto 16);
        last_o<=mem(rd mod G_DEPTH)(18);valid_o<='1';rd<=rd+1;
      end if;
    end if;
  end if;end process;
end;
