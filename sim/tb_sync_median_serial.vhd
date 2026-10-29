library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;
use work.sync_math_pkg.all;
entity tb_sync_median_serial is end;
architecture test of tb_sync_median_serial is
  signal clk:std_logic:='0';signal rst:std_logic:='1';signal sample,busy:std_logic:='0';
  signal values:hist_t:=(others=>(others=>'0'));
  signal result:signed(63 downto 0);
begin
  clk<=not clk after 8 ns;
  u:entity work.sync_median_serial port map(clk,rst,sample,values,result,busy);
  process
    variable test_values:hist_t;variable random:unsigned(63 downto 0):=x"8A01E5D290FDB347";
    variable elapsed:natural;
  begin
    wait until falling_edge(clk);rst<='0';
    for trial in 0 to 1023 loop
      for i in 0 to 7 loop
        random:=random(62 downto 0)&(random(63) xor random(62) xor random(60) xor random(59));
        if trial<8 then test_values(i):=to_signed((i+trial) mod 3-1,64);
        elsif trial=8 then test_values(i):=signed'(x"8000000000000000");
        elsif trial=9 then test_values(i):=signed'(x"7FFFFFFFFFFFFFFF");
        elsif trial=10 then
          if i mod 2=0 then test_values(i):=signed'(x"8000000000000000");else test_values(i):=signed'(x"7FFFFFFFFFFFFFFF");end if;
        else test_values(i):=signed(random);end if;
      end loop;
      values<=test_values;sample<='1';wait until falling_edge(clk);sample<='0';elapsed:=0;
      loop
        wait until falling_edge(clk);elapsed:=elapsed+1;exit when busy='0';
        assert elapsed<=43 report "Serial median missed its 43-clock deadline" severity failure;
      end loop;
      assert elapsed=43 report "Serial median latency changed" severity failure;
      assert result=median(test_values) report "Serial median differs from the parallel lower median" severity failure;
    end loop;
    -- Reset at every calculation position, including the last and a concurrent
    -- sample request, then reacquire without any stale rank or median state.
    for abort_after in 0 to 42 loop
      for i in 0 to 7 loop test_values(i):=to_signed((i-3)*(abort_after+2),64);end loop;
      values<=test_values;sample<='1';wait until falling_edge(clk);sample<='0';
      for i in 1 to abort_after loop wait until falling_edge(clk);end loop;
      rst<='1';if abort_after=42 then sample<='1';end if;
      wait until falling_edge(clk);
      assert busy='0' and result=0 report "Reset did not cancel an in-flight median" severity failure;
      rst<='0';sample<='0';wait until falling_edge(clk);
      sample<='1';wait until falling_edge(clk);sample<='0';
      for i in 1 to 43 loop wait until falling_edge(clk);end loop;
      assert busy='0' and result=median(test_values) report "Reset left stale median state" severity failure;
    end loop;
    report "PASS exact serial lower median: 1024 signed64 cases, ties, extrema, 43-clock deadline and 43 reset positions" severity note;stop;
  end process;
end;
