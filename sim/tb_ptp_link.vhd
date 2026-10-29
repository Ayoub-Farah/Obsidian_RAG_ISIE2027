library ieee;use ieee.std_logic_1164.all;use ieee.numeric_std.all;use std.env.all;
entity tb_ptp_link is end;
architecture test of tb_ptp_link is
  signal clk:std_logic:='0';signal rst:std_logic:='1';
  signal sd,md:std_logic_vector(15 downto 0):=(others=>'0');signal mk:std_logic_vector(1 downto 0);
  signal sv,sl,sr,mv,ml,idle:std_logic:='0';signal drops:unsigned(31 downto 0);
begin
  clk<=not clk after 8 ns;
  u:entity work.ptp_neighbor_link generic map(4)
    port map(clk,rst,10,to_unsigned(3,8),to_unsigned(1,32),to_unsigned(2,16),sd,"11",sv,sl,sr,md,mk,mv,ml,idle,drops);
  process
  begin
    wait until falling_edge(clk);rst<='0';
    for f in 0 to 3 loop for w in 0 to 3 loop
      sd<=std_logic_vector(to_unsigned(16*f+w,16));sv<='1';sl<='0';if w=3 then sl<='1';end if;
      loop wait until rising_edge(clk);exit when sr='1';end loop;
      wait until falling_edge(clk);
    end loop;end loop;
    sv<='0';sl<='0';wait;
  end process;
  process(clk)
    variable n:natural:=0;variable expected:natural;
  begin if rising_edge(clk) then
    if mv='1' then
      expected:=n mod 4;if n>=4 then expected:=expected+32;end if;
      assert unsigned(md)=expected and mk="11" report "Link lost/reordered words or dropped only part of a frame" severity failure;
      assert (ml='1')=(n mod 4=3) severity failure;n:=n+1;
    end if;
    if now>2 us then
      assert n=8 and drops=2 and idle='1' report "Wrong complete-frame loss accounting" severity failure;
      report "PASS link delay, FIFO backpressure, jitter, order and whole-frame losses" severity note;stop;
    end if;
  end if;end process;
end;
