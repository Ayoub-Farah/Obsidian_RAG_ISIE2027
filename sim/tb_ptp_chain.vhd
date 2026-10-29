library ieee;use ieee.std_logic_1164.all;use ieee.numeric_std.all;use std.env.all;
use work.ptp_emulation_pkg.all;
entity tb_ptp_chain is
  generic(G_NODES:positive:=3;G_PHASED:boolean:=false;G_ASYMMETRY:boolean:=false;G_DRIFT:integer:=0);
end;
architecture test of tb_ptp_chain is
  constant K:positive:=(G_NODES+2)/3;
  type board_words is array(0 to 2) of words64_t(0 to K-1);
  type board_flags is array(0 to 2) of std_logic_vector(0 to K-1);
  signal clk:std_logic_vector(0 to 2):=(others=>'0');signal rst:std_logic:='1';signal start,stop_req:std_logic:='0';
  signal ld,rd,lrx,rrx:words16_t(0 to 2);signal lk,rk,lrk,rrk:keeps_t(0 to 2);
  signal lv,rv,ll,rl,lready,rready,lrv,rrv,lrl,rrl,idle,overflow:std_logic_vector(0 to 2);
  signal times,corrections,theta,delays,ages:board_words;signal running,locked,holdover,errors,pulses:board_flags;
  signal raw:words64_t(0 to 2);
  function phase(b:natural)return time is
  begin if G_PHASED then return b*3 ns;else return 0 ns;end if;end;
  function step(b,i:natural)return unsigned is
    variable d:signed(79 downto 0);
  begin
    d:=shift_left(to_signed(G_DRIFT,80),32)/to_signed(1000000000,80);
    if (first_node(G_NODES,b)+i) mod 2=0 then d:=-d;end if;
    return resize(unsigned(shift_left(to_signed(1,80),32)+d),64);
  end;
begin
  boards:for b in 0 to 2 generate
    signal steps:steps_t(0 to K-1);signal offsets:offsets_t(0 to K-1):=(others=>(others=>'0'));
    signal fwd,rev:delays_t(0 to K-1):=(others=>1);
  begin
    process begin wait for phase(b);loop clk(b)<=not clk(b);wait for 8 ns;end loop;end process;
    params:for i in 0 to K-1 generate
      steps(i)<=step(b,i);fwd(i)<=3 when G_ASYMMETRY and first_node(G_NODES,b)+i>0 else 1;
    end generate;
    u:entity work.ptp_emulation_core generic map(K,G_NODES,5000)
      port map(clk(b),rst,'0',start,stop_req,'1',G_NODES,b,steps,offsets,fwd,rev,
        to_unsigned(0,8),to_unsigned(b+1,32),to_unsigned(0,16),1000,2,to_unsigned(0,64),64,
        lrx(b),rrx(b),lrk(b),rrk(b),lrv(b),lrl(b),rrv(b),rrl(b),
        ld(b),rd(b),lk(b),rk(b),lv(b),ll(b),rv(b),rl(b),lready(b),rready(b),raw(b),
        times(b),corrections(b),delays(b),theta(b),ages(b),open,open,open,open,open,open,
        running(b),locked(b),holdover(b),errors(b),pulses(b),open,open,idle(b),overflow(b));
    forward_physical:entity work.physical_link_model generic map(G_DELAY=>160 ns,G_PHASE=>b*19,G_DEPTH=>256)
      port map(clk(b),clk((b+1) mod 3),rst,rd(b),rk(b),rv(b),rl(b),rready(b),
        lrx((b+1) mod 3),lrk((b+1) mod 3),lrv((b+1) mod 3),lrl((b+1) mod 3));
    reverse_physical:entity work.physical_link_model generic map(G_DELAY=>160 ns,G_PHASE=>b*29,G_DEPTH=>256)
      port map(clk((b+1) mod 3),clk(b),rst,ld((b+1) mod 3),lk((b+1) mod 3),lv((b+1) mod 3),ll((b+1) mod 3),lready((b+1) mod 3),
        rrx(b),rrk(b),rrv(b),rrl(b));
  end generate;
  process begin wait for 132 ns;rst<='0';wait for 64 ns;start<='1';wait for 32 ns;start<='0';wait;end process;
  process
    variable ticks,nominal,first_running:natural:=0;variable all_run:boolean;
    variable previous:words64_t(0 to 2):=(others=>(others=>'0'));
    variable e:signed(63 downto 0);variable n:natural;
  begin
    wait until rising_edge(clk(0));wait for 1 ns;ticks:=ticks+1;all_run:=true;
    if rst='0' then
      if ticks mod 20000=0 then
        for b in 0 to 2 loop report "CHAIN_STATUS board="&integer'image(b)&" locked="&to_string(locked(b))&" running="&to_string(running(b))&" path="&to_hstring(delays(b)(0)) severity note;end loop;
      end if;
      assert overflow="000" report "Boundary capture overflow" severity failure;
      for b in 0 to 2 loop
        assert unsigned(raw(b))>=unsigned(previous(b)) report "Raw time moved backwards" severity failure;previous(b):=raw(b);
        for i in 0 to population(G_NODES,b)-1 loop
          assert errors(b)(i)='0' report "PTP engine error" severity failure;
          if running(b)(i)/='1' then all_run:=false;end if;
        end loop;
        for i in population(G_NODES,b) to K-1 loop
          assert running(b)(i)='0' and locked(b)(i)='0' report "Inactive slot participates" severity failure;
        end loop;
      end loop;
      if all_run then
        if first_running=0 then first_running:=ticks;end if;nominal:=nominal+1;
        if nominal mod 1000=0 then
          for b in 0 to 2 loop for i in 0 to population(G_NODES,b)-1 loop
            n:=first_node(G_NODES,b)+i;e:=signed(times(b)(i))-signed(times(0)(0));
            report "PTP_CSV,"&integer'image(ticks)&","&integer'image(n)&","&to_hstring(times(b)(i))&","&to_hstring(e)&","&to_hstring(corrections(b)(i))&","&to_hstring(theta(b)(i))&","&to_hstring(delays(b)(i)) severity note;
            if G_DRIFT=0 and not G_PHASED then
              if G_ASYMMETRY then
                assert abs(e+to_signed(n*65536,64))<=to_signed(G_NODES*65536/2,64) report "Asymmetry sign or accumulated bias is wrong" severity failure;
              else assert abs(e)<=to_signed(G_NODES*65536/2,64) report "Symmetric links impose an error slope" severity failure;end if;
            end if;
          end loop;end loop;
        end if;
        if nominal=12000 then
          assert locked(0)(0)='1' report "Anchor lost lock" severity failure;
          report "PASS PTP chain N="&integer'image(G_NODES)&" acquisition="&integer'image(first_running)&" independent-time samples=12" severity note;stop;
        end if;
      end if;
    end if;
    assert ticks<500000 report "PTP chain acquisition timeout" severity failure;
  end process;
end;
