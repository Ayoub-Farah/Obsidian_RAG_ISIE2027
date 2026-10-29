library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

entity tb_ptp_event_journal is end;
architecture test of tb_ptp_event_journal is
  signal clk:std_logic:='0';signal rst:std_logic:='1';
  signal ev:std_logic_vector(255 downto 0):=(others=>'0');
  signal total:natural range 0 to 4:=0;
  signal freeze,ack,frozen,ready:std_logic:='0';
  signal addr:unsigned(6 downto 0):=(others=>'0');
  signal data:std_logic_vector(63 downto 0);
  signal count,capture_count:natural range 0 to 32;
  signal lost,capture_lost:unsigned(31 downto 0);
  function record_value(seed:natural) return std_logic_vector is
    variable r:std_logic_vector(255 downto 0);
  begin
    for j in 0 to 3 loop r(64*j+63 downto 64*j):=std_logic_vector(to_unsigned(16*seed+j,64));end loop;
    return r;
  end;
begin
  clk<=not clk after 8 ns;
  u:entity work.ptp_event_journal port map(clk,rst,ev,total,freeze,ack,addr,data,frozen,ready,
    count,capture_count,lost,capture_lost);
  process
    procedure tick is begin wait until rising_edge(clk);wait for 1 ns;end;
    procedure check_counts(retained,discarded:natural) is
    begin
      assert count=retained and lost=discarded report "Journal retained/lost accounting mismatch" severity failure;
    end;
    procedure read_word(address:natural;expected:std_logic_vector(63 downto 0)) is
    begin
      addr<=to_unsigned(address,7);tick;
      assert data=expected report "Synchronous journal read differs at word "&integer'image(address) severity failure;
    end;
  begin
    tick;rst<='0';tick;
    check_counts(0,0);assert ready='1' and frozen='0' severity failure;
    ev<=record_value(1);total<=3;wait for 1 ns;
    assert capture_count=1 and capture_lost=2 report "Atomic capture omitted same-clock event/collisions" severity failure;
    tick;check_counts(1,2);
    total<=2;ev<=record_value(2);tick;check_counts(2,3);
    -- Consecutive events remain admissible, including the exact freeze edge.
    total<=1;ev<=record_value(3);freeze<='1';wait for 1 ns;
    assert capture_count=3 and capture_lost=3 severity failure;
    tick;freeze<='0';total<=0;
    assert frozen='1' and ready='0' report "Complete freeze-edge record was not committed" severity failure;
    check_counts(3,3);
    for n in 1 to 3 loop
      for j in 0 to 3 loop read_word(4*(n-1)+j,std_logic_vector(to_unsigned(16*n+j,64)));end loop;
    end loop;
    ev<=record_value(4);total<=3;tick;total<=2;tick;total<=0;check_counts(3,8);
    for n in 1 to 3 loop
      for j in 0 to 3 loop read_word(4*(n-1)+j,std_logic_vector(to_unsigned(16*n+j,64)));end loop;
    end loop;
    ack<='1';total<=2;tick;ack<='0';total<=0;wait for 1 ns;
    check_counts(0,10);assert frozen='0' and ready='1' report "ACK did not open a fresh journal" severity failure;
    -- Fill all 32 records on consecutive clocks: no serializer/busy loss.
    for n in 0 to 31 loop
      ev<=record_value(100+n);total<=1;tick;total<=0;
    end loop;
    check_counts(32,10);
    total<=4;tick;total<=0;check_counts(32,14);
    freeze<='1';tick;freeze<='0';assert frozen='1' severity failure;
    for n in 0 to 31 loop
      for j in 0 to 3 loop read_word(4*n+j,std_logic_vector(to_unsigned(16*(100+n)+j,64)));end loop;
    end loop;
    -- ACK on an open page drops/counts every coincident incoming event and
    -- leaves no pending RAM write to corrupt the next page's first record.
    ack<='1';tick;ack<='0';ev<=record_value(500);total<=1;tick;
    total<=3;ack<='1';tick;ack<='0';total<=0;check_counts(0,17);
    ev<=record_value(600);total<=1;freeze<='1';tick;total<=0;freeze<='0';
    assert frozen='1' severity failure;check_counts(1,17);
    for j in 0 to 3 loop read_word(j,std_logic_vector(to_unsigned(16*600+j,64)));end loop;
    -- Reset while events and a freeze request remain asserted. RAM may accept
    -- physical poison writes, but all logical state must remain empty and the
    -- first fresh record must replace every word on the first release edge.
    rst<='1';total<=4;freeze<='1';
    for n in 0 to 3 loop
      ev<=record_value(700+n);tick;check_counts(0,0);
      assert frozen='0' and ready='0' report "Reset-time audit became a retained record" severity failure;
    end loop;
    rst<='0';ev<=record_value(900);total<=3;wait for 1 ns;
    assert capture_count=1 and capture_lost=2 and ready='1'
      report "First post-reset audit/collision capture is incorrect" severity failure;
    tick;total<=0;freeze<='0';check_counts(1,2);
    assert frozen='1' report "First post-reset audit did not freeze atomically" severity failure;
    for j in 0 to 3 loop read_word(j,std_logic_vector(to_unsigned(16*900+j,64)));end loop;
    -- Fill and read every row again after reset, proving stale RAM is hidden
    -- until a complete new record has overwritten the corresponding row.
    ack<='1';tick;ack<='0';check_counts(0,2);
    for n in 0 to 31 loop
      ev<=record_value(1000+n);total<=1;if n=31 then freeze<='1';end if;tick;
    end loop;
    total<=0;freeze<='0';check_counts(32,2);assert frozen='1' severity failure;
    for n in 0 to 31 loop
      for j in 0 to 3 loop read_word(4*n+j,std_logic_vector(to_unsigned(16*(1000+n)+j,64)));end loop;
    end loop;
    report "PASS BRAM journal: one record per clock, synchronous reads, all 32 slots, atomic freeze, collision/full/frozen/ACK losses, events during reset and immediate fresh full-record overwrite" severity note;
    stop;
  end process;
end;
