library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.benchmark_pkg.all;
use std.env.all;
entity tb_codec_stream_crc is end;
architecture test of tb_codec_stream_crc is
 signal clk:std_logic:='0';signal rst:std_logic:='1';
 signal tick:unsigned(63 downto 0):=(others=>'0');signal tm:std_logic_vector(63 downto 0);
 signal req,tr,rv,rl:std_logic:='0';
 signal kind:std_logic_vector(7 downto 0):=x"10";
 signal seq:std_logic_vector(31 downto 0):=x"55667788";
 signal timestamp:std_logic_vector(63 downto 0):=x"0123456789ABCDEF";
 signal rd:std_logic_vector(15 downto 0):=(others=>'0');signal rk:std_logic_vector(1 downto 0):="11";
 signal ready,done,tv,tl,event,err,rready,rdone,rtv,rtl,revent,rerr:std_logic;
 signal td,rtd:std_logic_vector(15 downto 0);signal tk,rtk:std_logic_vector(1 downto 0);
 signal txstamp,rtxstamp,ts,rts,stamp,rstamp:std_logic_vector(63 downto 0);
 signal rxkind,rrxkind:std_logic_vector(7 downto 0);signal rxseq,rrxseq:std_logic_vector(31 downto 0);
 signal mode:natural range 0 to 4:=2;
 signal period:positive range 626 to 16777215:=6250;
 signal begin_tx,rbegin_tx:std_logic;
 signal txraw,rtxraw,rxraw,rrxraw:std_logic_vector(63 downto 0);
 signal good_events,bad_events:natural:=0;
begin
 clk<=not clk after 8 ns;tm<=std_logic_vector(shift_left(tick,16));
 tr<='0' when tick mod 7=0 or tick mod 11=0 else '1';
 process(clk)begin if rising_edge(clk)then tick<=tick+1;end if;end process;
 candidate:entity work.management_codec generic map(1,3,2,6250,G_RUNTIME_CONFIG=>true,G_EXTERNAL_STAMPS=>true,G_RUNTIME_TIMING=>true)
  port map(clk,rst,tm,req,kind,seq,timestamp,ready,done,txstamp,td,tk,tv,tl,tr,
   rd,rk,rv,rl,event,rxkind,rxseq,ts,stamp,err,mode,3,1,std_logic_vector(tick),std_logic_vector(tick-7),std_logic_vector(unsigned(tm)-to_unsigned(7*65536,64)),begin_tx,txraw,rxraw,period);
 reference:entity work.management_codec_stream_reference generic map(1,3,2,6250,G_RUNTIME_CONFIG=>true,G_EXTERNAL_STAMPS=>true,G_RUNTIME_TIMING=>true)
  port map(clk,rst,tm,req,kind,seq,timestamp,rready,rdone,rtxstamp,rtd,rtk,rtv,rtl,tr,
   rd,rk,rv,rl,revent,rrxkind,rrxseq,rts,rstamp,rerr,mode,3,1,std_logic_vector(tick),std_logic_vector(tick-7),std_logic_vector(unsigned(tm)-to_unsigned(7*65536,64)),rbegin_tx,rtxraw,rrxraw,period);
 process
 begin
  wait until falling_edge(clk);
  if rst='0' then
   assert std_logic_vector'(ready&done&tv&tl&event&err)=std_logic_vector'(rready&rdone&rtv&rtl&revent&rerr) report "Codec control differs from original" severity failure;
   assert txstamp=rtxstamp report "TX timestamp cadence changed" severity failure;
   assert begin_tx=rbegin_tx report "Accepted first-word cadence changed" severity failure;
   if begin_tx='1' then assert txraw=rtxraw report "Raw TX stamp changed" severity failure;end if;
   if event='1' then assert rxraw=rrxraw report "Raw RX stamp changed" severity failure;end if;
   if tv='1' then assert td=rtd and tk=rtk report "TX packet bytes differ from original" severity failure;end if;
   if event='1' then
    assert rxkind=rrxkind and rxseq=rrxseq and ts=rts and stamp=rstamp report "RX decode differs from original" severity failure;
    good_events<=good_events+1;
   end if;
   if err='1' then bad_events<=bad_events+1;end if;
  end if;
 end process;
 process
  type kinds_t is array(0 to 7) of natural;
  constant kinds:kinds_t:=(16,17,18,19,20,21,32,33);
  variable m:byte_array_t(0 to 43);variable h:byte_array_t(0 to 15);
  variable c:std_logic_vector(31 downto 0);variable k,pl,len,p:natural;
  type periods_t is array(0 to 3) of positive;constant periods:periods_t:=(626,1000,6250,16777215);
 begin
  wait for 64 ns;wait until falling_edge(clk);rst<='0';
  for trial in 0 to 127 loop
   p:=periods(trial mod 4);mode<=trial mod 5;period<=p;
   k:=kinds(trial mod 8);pl:=16;if k=32 then pl:=24;end if;len:=20+pl;
   m:=(others=>(others=>'0'));h:=make_header(k,0,3,pl,(others=>'0'));
   for j in 0 to 15 loop m(j):=h(j);end loop;
   for j in 16 to len-5 loop m(j):=std_logic_vector(to_unsigned((j*17+trial*7) mod 256,8));end loop;
   if k=32 then m(20):=std_logic_vector(to_unsigned(trial mod 5,8));for j in 0 to 3 loop m(36+j):=std_logic_vector(to_unsigned((p/(256**(3-j))) mod 256,8));end loop;end if;
   c:=x"FFFFFFFF";for j in 0 to len-5 loop c:=crc32_byte(c,m(j));end loop;c:=not c;
   for j in 0 to 3 loop m(len-4+j):=c(8*j+7 downto 8*j);end loop;
   if trial mod 4=1 then m(20):=m(20) xor x"01";end if;
   if trial mod 4=2 then len:=8;end if;
   wait until falling_edge(clk);kind<=std_logic_vector(to_unsigned(k,8));seq<=std_logic_vector(to_unsigned(trial,32));
   timestamp<=std_logic_vector(unsigned'(x"0123456789ABCDEF") xor shift_left(to_unsigned(trial*12345,64),19));req<='1';
   for w in 0 to len/2-1 loop
    rd<=m(2*w)&m(2*w+1);rk<="11";if trial mod 4=3 and w=5 then rk<="10";end if;
    rv<='1';if w=len/2-1 then rl<='1';else rl<='0';end if;
    wait until falling_edge(clk);req<='0';rv<='0';rl<='0';
    if w mod 3=0 then wait until falling_edge(clk);end if;
   end loop;
   for delay in 0 to 50 loop wait until falling_edge(clk);end loop;
  end loop;
  -- Abort a packet with a partially accumulated CRC, then request a fresh one.
  wait until falling_edge(clk);kind<=x"20";req<='1';wait until falling_edge(clk);req<='0';
  for j in 0 to 6 loop wait until falling_edge(clk);end loop;
  rst<='1';for j in 0 to 2 loop wait until falling_edge(clk);end loop;rst<='0';
  wait until falling_edge(clk);kind<=x"10";req<='1';wait until falling_edge(clk);req<='0';
  for j in 0 to 60 loop wait until falling_edge(clk);end loop;
  assert good_events>0 and bad_events>0 report "Equivalence test did not exercise both RX outcomes" severity failure;
  report "PASS streaming TX CRC cycle equivalence: runtime periods/modes, kinds, stalls, stamps, RX errors and mid-frame reset" severity note;
  stop;wait;
 end process;
end;
