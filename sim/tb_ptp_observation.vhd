library ieee;use ieee.std_logic_1164.all;use ieee.numeric_std.all;use std.env.all;
entity tb_ptp_observation is end;
architecture test of tb_ptp_observation is
  signal clk:std_logic:='0';signal rst:std_logic:='1';
  signal pulses:std_logic_vector(0 to 2):=(others=>'0');
  signal shadow,active:unsigned(15 downto 0):=(others=>'0');
  signal apply,ref,obs,valid,error:std_logic:='0';
  signal t:unsigned(63 downto 0):=(others=>'0');signal marker:std_logic;
  signal idx:unsigned(63 downto 0);signal skipped,backsteps:unsigned(31 downto 0);
begin
  clk<=not clk after 8 ns;
  u:entity work.ptp_observer generic map(3) port map(clk,rst,20,3,pulses,shadow,apply,'1','1',ref,obs,active,valid,error);
  m:entity work.ptp_epoch_marker port map(clk,rst,'1',std_logic_vector(t),shift_left(to_unsigned(100,64),16),626,4,marker,idx,skipped,backsteps);
  process
    procedure tick is begin wait until rising_edge(clk);wait for 1 ns;end;
    procedure commit(n:natural) is begin shadow<=to_unsigned(n,16);apply<='1';tick;apply<='0';tick;end;
  begin
    tick;rst<='0';tick;commit(20);tick;tick;
    assert valid='1' and active=20 severity failure;
    pulses(0)<='1';tick;assert ref='1' and obs='1' severity failure;
    commit(22);assert valid='0' and obs='1' report "Selection truncated a pulse" severity failure;
    pulses(2)<='1';pulses(0)<='0';tick;tick;tick;
    assert obs='0' and valid='0' report "Mux joined a target pulse" severity failure;
    pulses(2)<='0';tick;tick;assert valid='1' and active=22 severity failure;
    pulses(2)<='1';tick;assert obs='1' and ref='0' severity failure;
    commit(60);assert error='1' and active=22 and obs='1' report "Invalid selection changed the pin" severity failure;
    pulses(2)<='0';tick;
    -- Epoch crossing, backwards correction and skipped epochs.
    t<=shift_left(to_unsigned(99,64),16);tick;t<=shift_left(to_unsigned(100,64),16);tick;
    assert marker='1' report "No epoch marker" severity failure;
    for i in 0 to 5 loop tick;end loop;
    t<=shift_left(to_unsigned(90,64),16);tick;t<=shift_left(to_unsigned(100,64),16);tick;
    assert marker='0' and backsteps=1 report "Duplicate after a backward correction" severity failure;
    t<=shift_left(to_unsigned(2200,64),16);for i in 0 to 8 loop tick;end loop;
    assert skipped>0 report "Skipped epochs were hidden" severity failure;
    report "PASS observation atomic COMMIT, no truncation, no joined pulses, invalid IDs, epoch jumps" severity note;stop;
  end process;
end;
