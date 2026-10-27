library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;
entity tb_data_frame_filter is end;
architecture test of tb_data_frame_filter is
  signal clk:std_logic:='0';signal rst:std_logic:='1';
  signal rd,td:std_logic_vector(15 downto 0):=(others=>'0');signal rk,tk:std_logic_vector(1 downto 0):="11";
  signal rv,rl,tv,tl,tr,empty,overflow:std_logic:='0';signal hw:std_logic_vector(15 downto 0);
  signal count,got:natural:=0;
  signal rst2,rv2,rl2,tv2,tl2,tr2,e2,o2:std_logic:='0';signal rd2,td2,h2:std_logic_vector(15 downto 0):=(others=>'0');signal tk2:std_logic_vector(1 downto 0);
  signal tiny_done:std_logic:='0';
  type expected_t is array(natural range <>) of std_logic_vector(18 downto 0);
  -- Last | keep | data, excluding all management frames.
  constant EXPECTED:expected_t:=(
    std_logic_vector'('0'&"11"&x"C35A"),std_logic_vector'('0'&"11"&x"0101"),std_logic_vector'('0'&"11"&x"ABCD"),std_logic_vector'('1'&"10"&x"EE00"),
    std_logic_vector'('0'&"11"&x"C35A"),std_logic_vector'('0'&"11"&x"0103"),std_logic_vector'('1'&"11"&x"1234"),
    std_logic_vector'('0'&"11"&x"DEAD"),std_logic_vector'('0'&"11"&x"0111"),std_logic_vector'('1'&"11"&x"5678"),
    std_logic_vector'('1'&"11"&x"C35A"));
begin
  clk<=not clk after 8 ns;tr<='0' when count mod 11=1 or count mod 11=2 or count mod 11=3 else '1';
  dut:entity work.data_frame_filter generic map(32) port map(clk,rst,rd,rk,rv,rl,td,tk,tv,tl,tr,empty,overflow,hw);
  tiny:entity work.data_frame_filter generic map(2) port map(clk,rst2,rd2,"11",rv2,rl2,td2,tk2,tv2,tl2,tr2,e2,o2,h2);
  scoreboard:process(clk)
    variable n:natural:=0;variable held:boolean:=false;variable previous:std_logic_vector(18 downto 0);
  begin
    if rising_edge(clk) then
      count<=count+1;
      if rst='1' then n:=0;got<=0;held:=false;
      else
        if held then assert tv='1' and (tl&tk&td)=previous report "Filter changed stalled output" severity failure;end if;
        held:=tv='1' and tr='0';previous:=tl&tk&td;
        if tv='1' and tr='1' then
          assert n<EXPECTED'length report "Management frame leaked into DATA" severity failure;
          assert (tl&tk&td)=EXPECTED(n) report "Filter changed/reordered DATA word "&integer'image(n) severity failure;
          n:=n+1;got<=n;
        end if;
        assert overflow='0' report "Filter overflow with admissible load" severity failure;
      end if;
    end if;
  end process;
  main:process
    procedure word(v:std_logic_vector(15 downto 0);last:std_logic:='0';keep:std_logic_vector(1 downto 0):="11";pause:natural:=0) is
    begin
      wait until falling_edge(clk);rv<='0';
      for k in 1 to pause loop wait until falling_edge(clk);end loop;
      rd<=v;rk<=keep;rl<=last;rv<='1';wait until rising_edge(clk);
    end procedure;
  begin
    wait for 64 ns;wait until falling_edge(clk);rst<='0';
    word(x"C35A");word(x"0101",pause=>3);word(x"ABCD");word(x"EE00",'1',"10");
    -- Management between DATA frames, including gaps inside its first two words.
    word(x"C35A");word(x"0110",pause=>4);word(x"F001");word(x"F002");word(x"F003",'1');
    word(x"C35A");word(x"0103");word(x"1234",'1');
    -- Invalid magic must be delivered to the DATA parser for rejection.
    word(x"DEAD");word(x"0111");word(x"5678",'1');
    word(x"C35A",'1');
    -- A second complete management frame after a malformed short DATA frame.
    word(x"C35A");word(x"0120");word(x"F004",'1');
    wait until falling_edge(clk);rv<='0';rl<='0';
    for timeout in 0 to 200 loop wait until rising_edge(clk);exit when empty='1';end loop;
    assert empty='1' and got=EXPECTED'length report "Filter did not drain exactly all DATA frames" severity failure;
    if tiny_done/='1' then wait until tiny_done='1';end if;
    report "PASS tb_data_frame_filter: classification, header pauses, frame lock, DATA/mgmt interleave, backpressure and overflow" severity note;stop;wait;
  end process;
  tiny_test:process
    procedure word2(v:std_logic_vector(15 downto 0);last:std_logic:='0') is
    begin wait until falling_edge(clk);rd2<=v;rl2<=last;rv2<='1';wait until rising_edge(clk);end;
  begin
    rst2<='1';wait until falling_edge(clk);wait until falling_edge(clk);rst2<='0';tr2<='0';
    word2(x"C35A");word2(x"0101");word2(x"BEEF",'1');
    wait until falling_edge(clk);rv2<='0';
    assert o2='1' and unsigned(h2)=2 and tv2='1' and td2=x"C35A" report "Tiny filter failed to flag overflow and hold head" severity failure;
    for k in 0 to 10 loop wait until rising_edge(clk);assert o2='1' report "Overflow was not sticky" severity failure;end loop;
    -- Explicit reset is required after loss; no damaged transaction is reused.
    wait until falling_edge(clk);rst2<='1';wait until falling_edge(clk);rst2<='0';tr2<='1';
    word2(x"C35A");word2(x"0101",'1');wait until falling_edge(clk);rv2<='0';
    for k in 0 to 10 loop wait until rising_edge(clk);end loop;
    assert e2='1' and o2='0' report "Filter failed to recover after explicit reset" severity failure;
    tiny_done<='1';wait;
  end process;
end;
