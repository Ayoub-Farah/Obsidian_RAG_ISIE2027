-- Single clock FIFO: synchronous BRAM read, registered output, one beat/cycle.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity physical_fifo is
  generic(G_DEPTH:positive:=8192; G_WIDTH:positive:=18);
  port(clk_i,rst_i:in std_logic; data_i:in std_logic_vector(G_WIDTH-1 downto 0);
    valid_i:in std_logic; data_o:out std_logic_vector(G_WIDTH-1 downto 0);
    valid_o:out std_logic; ready_i:in std_logic; empty_o,overflow_o:out std_logic;
    level_o:out unsigned(15 downto 0));
end;
architecture rtl of physical_fifo is
  type mem_t is array(0 to G_DEPTH-1) of std_logic_vector(G_WIDTH-1 downto 0);
  signal mem:mem_t;
  attribute ram_style:string; attribute ram_style of mem:signal is "block";
  signal rd,wr:natural range 0 to G_DEPTH-1:=0;
  signal used:natural range 0 to G_DEPTH:=0;
  signal q:std_logic_vector(G_WIDTH-1 downto 0):=(others=>'0');
  signal qv,overflow:std_logic:='0';
  function advance(n:natural) return natural is begin if n=G_DEPTH-1 then return 0;else return n+1;end if;end;
begin
  data_o<=q;valid_o<=qv;overflow_o<=overflow;
  empty_o<='1' when used=0 and qv='0' else '0';
  level_o<=to_unsigned(used,16)+("000000000000000" & qv);
  process(clk_i)
    variable take,put:boolean;
  begin
    if rising_edge(clk_i) then
      if rst_i='1' then rd<=0;wr<=0;used<=0;qv<='0';overflow<='0';
      else
        take:=used>0 and (qv='0' or ready_i='1');
        put:=valid_i='1' and (used<G_DEPTH or take);
        if qv='1' and ready_i='1' then qv<='0';end if;
        if take then q<=mem(rd);qv<='1';rd<=advance(rd);end if;
        if put then mem(wr)<=data_i;wr<=advance(wr);
        elsif valid_i='1' then overflow<='1';end if;
        if put and not take then used<=used+1;elsif take and not put then used<=used-1;end if;
      end if;
    end if;
  end process;
end;
