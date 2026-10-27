library ieee;use ieee.std_logic_1164.all;use ieee.numeric_std.all;use std.env.all;
entity tb_sync_system is generic(G_TEST_MISS:boolean:=false;G_STALL:boolean:=false;G_TEST_STOP:boolean:=false;G_TEST_DEADLINE:boolean:=false;G_DRIFT_PPB:integer:=0;G_REAL_PERIOD:boolean:=false;G_TEST_BOUNDED:boolean:=false;G_TEST_RESTART:boolean:=false;G_TEST_HELD_START:boolean:=false);end;
architecture test of tb_sync_system is
 function choose(a,b:natural;sel:boolean)return natural is begin if sel then return a;else return b;end if;end;
 function drift(i:natural)return integer is begin if i=0 then return 0;elsif i=1 then return G_DRIFT_PPB;else return -G_DRIFT_PPB;end if;end;
 constant C_PERIOD:natural:=choose(6250,1000,G_REAL_PERIOD);constant C_WINDOW:natural:=choose(625,500,G_REAL_PERIOD);constant C_INTERVAL:natural:=choose(10,2,G_REAL_PERIOD);constant C_CYCLES:natural:=choose(12,4,G_REAL_PERIOD);
 type a16 is array(0 to 2)of std_logic_vector(15 downto 0);type a2 is array(0 to 2)of std_logic_vector(1 downto 0);type a32 is array(0 to 2)of std_logic_vector(31 downto 0);type a64 is array(0 to 2)of std_logic_vector(63 downto 0);
 signal clk:std_logic:='0';signal rst:std_logic_vector(0 to 2):=(others=>'1');signal start:std_logic_vector(0 to 2):=(others=>'0');signal restart:std_logic_vector(0 to 2):=(others=>'0');
 signal ld,rd,lrx,rrx:a16;signal lk,rk,lkr,rkr:a2;signal lv,rv,ll,rl,lvr,rvr,llr,rlr,launch,locked,run,mgmt,err:std_logic_vector(0 to 2);signal cycle:a32;signal raw,logic,offs,path:a64;signal misses:a32;
 type delay16 is array(0 to 4)of a16;type delay2 is array(0 to 4)of a2;type delaybit is array(0 to 4)of std_logic_vector(0 to 2);
 signal dl,dr:delay16;signal kl,kr:delay2;signal vl,vr,el,er:delaybit:=(others=>(others=>'0'));
 signal ticks:natural:=0;signal idle:std_logic:='1';signal stop_req:std_logic:='0';signal txready:std_logic:='1';
begin clk<=not clk after 8 ns;txready<='0' when G_STALL and ticks mod 7=0 else '1';
 n:for i in 0 to 2 generate
 u:entity work.sync_system generic map(G_NODE_ID=>i,G_NODES=>3,G_MODE=>2,G_PERIOD_CYCLES=>C_PERIOD,G_ARM_DELAY_CYCLES=>2000,G_SYNC_INTERVAL=>C_INTERVAL,G_WINDOW_CYCLES=>C_WINDOW,G_LOCK_SAMPLES=>8,G_EXCHANGE_SPACING=>200,G_DRIFT_PPB=>drift(i),G_RUN_CYCLES=>choose(3,128,G_TEST_BOUNDED or G_TEST_RESTART or G_TEST_HELD_START))
 port map(clk,rst(i),start(i) or restart(i),stop_req,'1',idle,lrx(i),lkr(i),lvr(i),llr(i),rrx(i),rkr(i),rvr(i),rlr(i),ld(i),lk(i),lv(i),ll(i),txready,rd(i),rk(i),rv(i),rl(i),txready,launch(i),cycle(i),run(i),locked(i),mgmt(i),raw(i),logic(i),offs(i),path(i),misses(i),err(i));
 lrx(i)<=dr(4)((i+2)mod 3);lkr(i)<=kr(4)((i+2)mod 3);lvr(i)<=vr(4)((i+2)mod 3);llr(i)<=er(4)((i+2)mod 3);
 rrx(i)<=dl(4)((i+1)mod 3);rkr(i)<=kl(4)((i+1)mod 3);rvr(i)<=vl(4)((i+1)mod 3);rlr(i)<=el(4)((i+1)mod 3);
 end generate;
 process(clk)begin if rising_edge(clk)then ticks<=ticks+1;dl(0)<=ld;dr(0)<=rd;kl(0)<=lk;kr(0)<=rk;for i in 0 to 2 loop vl(0)(i)<=lv(i) and txready;vr(0)(i)<=rv(i) and txready;end loop;el(0)<=ll;er(0)<=rl;for j in 1 to 4 loop dl(j)<=dl(j-1);dr(j)<=dr(j-1);kl(j)<=kl(j-1);kr(j)<=kr(j-1);vl(j)<=vl(j-1);vr(j)<=vr(j-1);el(j)<=el(j-1);er(j)<=er(j-1);end loop;end if;end process;
 process begin wait for 100 ns;rst(0)<='0';wait for 32 ns;rst(1)<='0';wait for 32 ns;rst(2)<='0';wait for 100 ns;start(0)<='1';wait for 16 ns;if not G_TEST_HELD_START then start(0)<='0';end if;wait;end process;
 process(clk)variable prev:a64:=(others=>(others=>'0'));variable count:natural:=0;variable first0,first1,first2:natural:=0;variable c0,c1,c2:natural:=0;variable busy_start:natural:=0;variable tested:boolean:=false;variable stopped:boolean:=false;variable stop_at:natural:=0;
 begin if rising_edge(clk)then
 restart<=(others=>'0');
 for i in 0 to 2 loop if rst(i)='0' and unsigned(raw(i))>1 then assert unsigned(raw(i))=unsigned(prev(i))+1 report "Raw counter changed by PTP" severity failure;end if;prev(i):=raw(i);end loop;
 if launch(0)='1' then first0:=ticks;c0:=c0+1;end if;if launch(1)='1' then first1:=ticks;c1:=c1+1;end if;if launch(2)='1' then first2:=ticks;c2:=c2+1;end if;
 if G_TEST_MISS and c0=2 and not tested then busy_start:=first0;tested:=true;end if;
 if tested and ticks>=busy_start+450 and ticks<busy_start+900 then idle<='0';else idle<='1';end if;
 if ((G_TEST_STOP and c0=3) or (G_TEST_DEADLINE and c0=2) or ((G_TEST_BOUNDED or G_TEST_RESTART or G_TEST_HELD_START) and c0=3)) and not stopped then stopped:=true;stop_at:=ticks;end if;
 if G_TEST_STOP and stopped then
 if ticks=stop_at+10 then stop_req<='1';idle<='0';elsif ticks=stop_at+11 then stop_req<='0';end if;
 if ticks>=stop_at+10 and ticks<stop_at+300 then
 if ticks>stop_at+12 then assert run="111" and mgmt="000" report "Stop preempted an in-flight data window" severity failure;end if;idle<='0';
 elsif ticks=stop_at+300 then idle<='1';
 elsif ticks=stop_at+400 then assert run="000" and mgmt="111" report "Stop did not finish after drain" severity failure;report "PASS graceful stop drains before switching to management" severity note;stop;end if;
 end if;
 if G_TEST_DEADLINE and stopped then
 if ticks>=stop_at+10 and ticks<stop_at+1600 then idle<='0';
 if ticks>stop_at+1100 then assert err="111" and run="111" and mgmt="000" report "Deadline failure preempted an in-flight frame" severity failure;end if;
 elsif ticks=stop_at+1600 then idle<='1';
 elsif ticks=stop_at+1700 then assert run="000" and err="111" and c0=2 and c1=2 and c2=2 report "Deadline did not suppress new launch and drain" severity failure;report "PASS deadline invalidates cycle and drains before stopping" severity note;stop;end if;
 end if;
 if G_TEST_HELD_START and stopped and ticks=stop_at+3200 then assert run="000" and err="000" and c0=3 and c1=3 and c2=3 report "Held-high START restarted bounded campaign" severity failure;report "PASS held-high START executes exactly three cycles and remains stopped" severity note;stop;end if;
 if G_TEST_RESTART and stopped and ticks=stop_at+1200 then assert run="000" and err="000" report "First bounded campaign did not finish cleanly" severity failure;restart(0)<='1';end if;
 if G_TEST_RESTART and c0=6 and c1=6 and c2=6 then assert locked="111" and err="000" report "Second campaign failed to reacquire" severity failure;report "PASS stopped campaign rearms without resetting raw clocks" severity note;stop;end if;
 if G_TEST_BOUNDED and stopped and ticks>stop_at+1200 then assert run="000" and err="000" and c0=3 and c1=3 and c2=3 report "Bounded campaign did not stop at configured cycle count" severity failure;report "PASS bounded campaign completes three cycles and stops at common next epoch" severity note;stop;end if;
 if not G_TEST_STOP and not G_TEST_DEADLINE and not G_TEST_BOUNDED and not G_TEST_RESTART and not G_TEST_HELD_START and c0>=C_CYCLES and c1>=C_CYCLES and c2>=C_CYCLES then
 assert locked="111" report "Chain not locked" severity failure;
 assert err="000" report "Unexpected synchronization failure" severity failure;
 if G_DRIFT_PPB=0 then assert first0=first1 and first1=first2 report "Unaligned launches in symmetric common-clock test" severity failure;
 else assert abs(integer(first0)-integer(first1))<=4 and abs(integer(first0)-integer(first2))<=4 report "Launch skew exceeds four ticks" severity failure;end if;
 for i in 0 to 2 loop
 if G_TEST_MISS then assert unsigned(misses(i))=1 report "Missing explicit occupied-window event" severity failure;
 else assert unsigned(misses(i))=0 report "Unexpected maintenance miss" severity failure;end if;end loop;
 report "PASS sync: sequential 3-node acquisition, READY/ARM, aligned launches, maintenance, raw monotonic" severity note;stop;
 end if;
 if G_REAL_PERIOD and abs(G_DRIFT_PPB)>=50000 and err/="000" then
 report "PASS high-drift sensitivity: explicit failure rather than silent admission" severity note;stop;end if;
 if ticks=200000 then report "locked="&to_string(locked)&" run="&to_string(run)&" err="&to_string(err)&" launches="&integer'image(c0)&","&integer'image(c1)&","&integer'image(c2) severity note;assert false report "Synchronization timeout" severity failure;end if;
 end if;end process;
end;
