library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;
entity tb_filter_equivalence is
 generic(G_WORDS:positive:=16);
end;
architecture test of tb_filter_equivalence is
 signal clk:std_logic:='0';
 signal rst,rv,rl,tr:std_logic:='0';
 signal rd:std_logic_vector(15 downto 0):=(others=>'0');
 signal rk:std_logic_vector(1 downto 0):="11";
 signal a,b:std_logic_vector(18 downto 0);
 signal av,bv,ae,be,ao,bo:std_logic;
 signal ah,bh:std_logic_vector(15 downto 0);
begin
 clk<=not clk after 8 ns;
 candidate:entity work.data_frame_filter generic map(G_WORDS)
  port map(clk,rst,rd,rk,rv,rl,a(15 downto 0),a(17 downto 16),av,a(18),tr,ae,ao,ah);
 reference:entity work.data_frame_filter_reference generic map(G_WORDS)
  port map(clk,rst,rd,rk,rv,rl,b(15 downto 0),b(17 downto 16),bv,b(18),tr,be,bo,bh);
 process
  variable rng:unsigned(31 downto 0):=x"A15B4C93";
  variable position,nwords:natural:=0;
  variable magic,mgmt:boolean;
 begin
  rst<='1';wait until falling_edge(clk);wait until falling_edge(clk);rst<='0';
  for cycle in 0 to 50000 loop
   rng:=rng(30 downto 0)&(rng(31) xor rng(21) xor rng(1) xor rng(0));
   rv<='0';rl<='0';tr<=rng(8) or rng(9);
   -- Long stalls, resets, full queues and repeated descriptor reuse.
   if cycle mod 4096<256 then tr<='0';end if;
   if cycle mod 4096=2048 then rst<='1';position:=0;
   elsif cycle mod 4096=2049 then rst<='0';end if;
   if rng(0)='1' or rng(1)='1' then
    rv<='1';rk<=std_logic_vector(rng(12 downto 11));
    if position=0 then
     nwords:=1+to_integer(rng(6 downto 2));magic:=rng(13)='1';mgmt:=rng(14)='1';
     if magic then rd<=x"C35A";rk<="11";else rd<=std_logic_vector(rng(31 downto 16));end if;
    elsif position=1 then
     if mgmt then rd<=x"0110";else rd<=x"0101";end if;
    else rd<=std_logic_vector(rng(31 downto 16));end if;
    if position+1=nwords then rl<='1';position:=0;else position:=position+1;end if;
   end if;
   wait until rising_edge(clk);wait for 1 ns;
   assert av=bv and ae=be and ao=bo and ah=bh report "Filter control mismatch at cycle "&integer'image(cycle) severity failure;
   if av='1' then assert a=b report "Filter word mismatch at cycle "&integer'image(cycle) severity failure;end if;
   wait until falling_edge(clk);
  end loop;
  report "PASS filter cycle equivalence, FIFO words="&integer'image(G_WORDS) severity note;
  stop;wait;
 end process;
end;
