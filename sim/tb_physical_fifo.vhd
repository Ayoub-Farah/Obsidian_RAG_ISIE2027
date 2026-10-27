library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;
entity tb_physical_fifo is end;
architecture test of tb_physical_fifo is
  signal clk:std_logic:='0';signal rst:std_logic:='1';signal valid,ready,qvalid,empty,overflow:std_logic:='0';
  signal d,q:std_logic_vector(17 downto 0);signal level:unsigned(15 downto 0);
begin
  clk<=not clk after 8 ns;
  dut:entity work.physical_fifo port map(clk,rst,d,valid,q,qvalid,ready,empty,overflow,level);
  process
    variable expected:natural:=0;
  begin
    wait for 128 ns;wait until falling_edge(clk);rst<='0';
    -- Three maximum frames can be buffered while the physical egress stops.
    for i in 0 to 6197 loop d<=std_logic_vector(to_unsigned(i,18));valid<='1';wait until falling_edge(clk);end loop;
    valid<='0';wait until falling_edge(clk);assert overflow='0' and level=6198 report "Three-frame capacity missing" severity failure;
    for i in 0 to 9 loop wait until falling_edge(clk);assert qvalid='1' and unsigned(q)=0 report "FIFO changed under stall" severity failure;end loop;
    ready<='1';
    while expected<6198 loop
      wait until rising_edge(clk);
      if qvalid='1' then assert unsigned(q)=expected report "BRAM FIFO reorder" severity failure;expected:=expected+1;end if;
    end loop;
    wait until falling_edge(clk);ready<='0';wait until falling_edge(clk);assert empty='1' report "FIFO did not drain" severity failure;
    for i in 0 to 8193 loop d<=std_logic_vector(to_unsigned(i,18));valid<='1';wait until falling_edge(clk);end loop;
    valid<='0';wait until falling_edge(clk);assert overflow='1' report "FIFO overflow hidden" severity failure;
    report "PASS tb_physical_fifo";stop;wait;
  end process;
end;
