library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;
use work.benchmark_pkg.all;
entity tb_links is end;
architecture test of tb_links is
  signal clk:std_logic:='0';signal rst:std_logic:='1';
  signal sd,md:word_array_t(0 to 1);signal sk,mk:keep_array_t(0 to 1);
  signal sv,sl,sr,mv,ml,empty:std_logic_vector(0 to 1):=(others=>'0');
  signal hw:word_array_t(0 to 1);
  type counts_t is array(0 to 1) of natural range 0 to 64;
  signal sent,received:counts_t:=(others=>0);
  signal enable:std_logic:='0';signal phase:natural:=0;signal limit_words:natural:=2;
  signal crst,cinv,cinl,coutv,coutl,coutready,cempty,capture_overflow:std_logic:='0';
  signal cind,coutd:std_logic_vector(15 downto 0):=(others=>'0');
  signal cink,coutk:std_logic_vector(1 downto 0):="11";signal chw:std_logic_vector(15 downto 0);
  signal capture_done:std_logic:='0';
begin
  clk<=not clk after 8 ns;
  cap:entity work.aurora_rx_capture generic map(G_WORDS=>2)
    port map(clk,crst,cind,cink,cinv,cinl,coutd,coutk,coutv,coutl,coutready,cempty,capture_overflow,chw);
  links:for i in 0 to 1 generate
  begin
    link:entity work.virtual_neighbor_link generic map(G_LATENCY_CYCLES=>9,G_FIFO_WORDS=>4,G_FRAME_GAP_CYCLES=>2,G_CC_PERIOD=>17,G_CC_LENGTH=>6,G_CC_PHASE=>9*i)
      port map(clk,rst,sd(i),sk(i),sv(i),sl(i),sr(i),md(i),mk(i),mv(i),ml(i),empty(i),hw(i));
    sd(i)<=std_logic_vector(to_unsigned(4096+phase*8192+i*256+sent(i),16));
    sk(i)<="10" when sent(i) mod 5=4 else "11";
    sl(i)<='1' when sent(i) mod 5=4 else '0';
    sv(i)<='1' when enable='1' and sent(i)<limit_words else '0';
    scoreboard:process(clk)
      type exp_t is array(0 to 63) of std_logic_vector(18 downto 0);
      type times_t is array(0 to 63) of natural;
      variable expected:exp_t;variable accepted_at:times_t;
      variable w,r,t:natural:=0;
      variable was_stalled:boolean:=false;
      variable oldword:std_logic_vector(18 downto 0);
    begin
      if rising_edge(clk) then
        if rst='1' then sent(i)<=0;received(i)<=0;w:=0;r:=0;t:=0;was_stalled:=false;
        else
          t:=t+1;
          if was_stalled then assert sv(i)='1' and sl(i)&sk(i)&sd(i)=oldword report "Source was not stable under virtual link stall" severity failure;end if;
          was_stalled:=sv(i)='1' and sr(i)='0';oldword:=sl(i)&sk(i)&sd(i);
          if sv(i)='1' and sr(i)='1' then
            expected(w):=sl(i)&sk(i)&sd(i);accepted_at(w):=t;w:=w+1;sent(i)<=w;
          end if;
          if mv(i)='1' then
            assert r<w report "Virtual link emitted an unaccepted or stale word after reset" severity failure;
            assert ml(i)&mk(i)&md(i)=expected(r) report "Virtual link lost/reordered/corrupted a word" severity failure;
            assert t-accepted_at(r)>=9 report "Virtual link latency shorter than configured" severity failure;
            r:=r+1;received(i)<=r;
          end if;
        end if;
      end if;
    end process;
  end generate;
  capture_test:process
    procedure beat(d:natural;last:std_logic) is
    begin wait until falling_edge(clk);cind<=std_logic_vector(to_unsigned(d,16));cinv<='1';cinl<=last;wait until rising_edge(clk);end;
  begin
    crst<='1';wait until falling_edge(clk);wait until falling_edge(clk);crst<='0';coutready<='0';
    beat(16#1001#,'0');beat(16#1002#,'0');beat(16#1003#,'0');beat(16#1004#,'1');
    wait until falling_edge(clk);cinv<='0';
    assert capture_overflow='1' and unsigned(chw)=2 and coutv='1' and coutd=x"1001" report "Capture full overflow/stable head incorrect" severity failure;
    for stall in 0 to 8 loop wait until rising_edge(clk);assert coutv='1' and coutd=x"1001" and coutl='0' report "Capture word changed under stall" severity failure;end loop;
    wait until falling_edge(clk);coutready<='1';wait until rising_edge(clk);wait for 1 ns;
    assert coutv='1' and coutd=x"1002" report "Capture lost admitted second word" severity failure;
    wait until rising_edge(clk);wait for 1 ns;assert cempty='1' and capture_overflow='1' report "Capture did not empty or overflow not sticky" severity failure;
    -- A reset in a partial frame clears all old words and the sticky error.
    wait until falling_edge(clk);crst<='1';wait until falling_edge(clk);crst<='0';coutready<='0';
    beat(16#2001#,'0');beat(16#2002#,'0');
    -- Full plus simultaneous read/write must accept the replacement word.
    wait until falling_edge(clk);coutready<='1';cind<=x"2003";cinv<='1';cinl<='1';
    wait until rising_edge(clk);wait until falling_edge(clk);cinv<='0';
    assert capture_overflow='0' and coutd=x"2002" report "Capture falsely overflowed on simultaneous full read/write" severity failure;
    wait until rising_edge(clk);wait for 1 ns;assert coutd=x"2003" and coutl='1' report "Capture replacement word missing" severity failure;
    wait until rising_edge(clk);wait until falling_edge(clk);coutready<='0';
    beat(16#3001#,'0');wait until falling_edge(clk);cinv<='0';crst<='1';wait until falling_edge(clk);crst<='0';
    assert cempty='1' and capture_overflow='0' report "Capture reset failed to discard partial frame" severity failure;
    capture_done<='1';wait;
  end process;
  run:process
  begin
    wait for 64 ns;wait until falling_edge(clk);rst<='0';enable<='1';limit_words<=2;
    wait until sent(0)=2 and sent(1)=2;
    -- Interrupt each independent link part-way through its first frame.
    wait until falling_edge(clk);rst<='1';enable<='0';
    wait until falling_edge(clk);wait until falling_edge(clk);phase<=1;limit_words<=40;rst<='0';enable<='1';
    for timeout in 0 to 3000 loop
      wait until rising_edge(clk);exit when received(0)=40 and received(1)=40;
    end loop;
    assert sent(0)=40 and sent(1)=40 and received(0)=40 and received(1)=40 report "Independent CC-phase links failed to drain" severity failure;
    wait until falling_edge(clk);enable<='0';
    assert empty="11" and unsigned(hw(0))<=4 and unsigned(hw(1))<=4 report "Link empty/highwater incorrect" severity failure;
    if capture_done/='1' then wait until capture_done='1';end if;
    report "PASS tb_links: finite FIFO, full read/write, overflow, stall, independent CC phases, partial-frame resets" severity note;
    stop;wait;
  end process;
end;
