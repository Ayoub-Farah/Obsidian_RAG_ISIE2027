-- Non-backpressured classifier with lookahead, including gaps in RX valid.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity physical_rx_router is
  port(clk_i,rst_i:in std_logic;raw_i:in unsigned(63 downto 0);
    data_i:in std_logic_vector(15 downto 0);keep_i:in std_logic_vector(1 downto 0);
    valid_i,last_i:in std_logic;
    data_o:out std_logic_vector(15 downto 0);keep_o:out std_logic_vector(1 downto 0);
    data_valid_o,sync_valid_o,control_valid_o,last_o:out std_logic;
    stamp_o:out unsigned(63 downto 0);busy_o,error_o:out std_logic);
end;
architecture rtl of physical_rx_router is
  signal pd:std_logic_vector(15 downto 0):=(others=>'0');
  signal pk:std_logic_vector(1 downto 0):=(others=>'0');
  signal pt:unsigned(63 downto 0):=(others=>'0');
  signal pending,pl,pfirst,ov:std_logic:='0';
  signal index:natural range 0 to 2:=0;
  signal magic:std_logic_vector(15 downto 0):=(others=>'0');
  signal proute,oroute:natural range 0 to 3:=0;
  signal fault:std_logic:='0';
begin
  error_o<=fault;
  data_valid_o<=ov when oroute=1 else '0';sync_valid_o<=ov when oroute=2 else '0';
  control_valid_o<=ov when oroute=3 else '0';
  busy_o<='1' when index/=0 or pending='1' or ov='1' else '0';
  process(clk_i)
    variable route:natural range 0 to 3;
  begin if rising_edge(clk_i) then
    ov<='0';route:=proute;
    if rst_i='1' then index<=0;proute<=0;oroute<=0;fault<='0';pending<='0';
    else
      if pending='1' and (valid_i='1' or pl='1') then
        if pfirst='1' and pl='0' then
          if magic=x"D3A7" and data_i(15 downto 8)=x"01" then route:=3;
          elsif magic=x"C35A" and data_i(15 downto 8)=x"02" then route:=1;
          elsif magic=x"C35A" and data_i(15 downto 8)=x"01" then route:=2;
          else route:=0;fault<='1';end if;
        end if;
        data_o<=pd;keep_o<=pk;last_o<=pl;stamp_o<=pt;oroute<=route;ov<='1';pending<='0';
      end if;
      if valid_i='1' then
        pd<=data_i;pk<=keep_i;pl<=last_i;pt<=raw_i;pending<='1';pfirst<='0';
        if index=0 then
          magic<=data_i;index<=1;pfirst<='1';route:=0;
          if last_i='1' then fault<='1';index<=0;end if;
        elsif index=1 then index<=2;end if;
        if last_i='1' then index<=0;end if;
        proute<=route;
      end if;
    end if;
  end if;end process;
end;
