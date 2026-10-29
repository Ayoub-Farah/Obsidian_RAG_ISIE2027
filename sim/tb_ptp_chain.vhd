library ieee;use ieee.std_logic_1164.all;use ieee.numeric_std.all;use std.env.all;
use work.ptp_emulation_pkg.all;
entity tb_ptp_chain is
  generic(G_NODES:positive:=3;G_PHASED:boolean:=false;G_ASYMMETRY:boolean:=false;G_DRIFT:integer:=0;
    G_SEED:positive:=1;G_JITTER_MASK:natural range 0 to 255:=0;G_DROP_EVERY:natural range 0 to 65535:=0;
    G_NOMINAL_SAMPLES:positive:=12;G_SAMPLE_SPACING:positive:=1000;G_CAPACITY_CSV:boolean:=false);
end;
architecture test of tb_ptp_chain is
  constant K:positive:=(G_NODES+2)/3;
  type board_words is array(0 to 2) of words64_t(0 to K-1);
  type board_flags is array(0 to 2) of std_logic_vector(0 to K-1);
  type board_counts is array(0 to 2) of words32_t(0 to K-1);
  signal clk:std_logic_vector(0 to 2):=(others=>'0');signal rst:std_logic:='1';signal start,stop_req:std_logic:='0';
  signal ld,rd,lrx,rrx:words16_t(0 to 2);signal lk,rk,lrk,rrk:keeps_t(0 to 2);
  signal lv,rv,ll,rl,lready,rready,lrv,rrv,lrl,rrl,idle,overflow:std_logic_vector(0 to 2);
  signal times,corrections,theta,delays,ages:board_words;signal running,locked,holdover,errors,pulses:board_flags;
  signal raw:words64_t(0 to 2);
  signal accepted,rejected,dropped:board_counts;
  function phase(b:natural)return time is
  begin if G_PHASED then return b*3 ns;else return 0 ns;end if;end;
  function step(b,i:natural)return unsigned is
    variable d:signed(79 downto 0);
  begin
    d:=shift_left(to_signed(G_DRIFT,80),32)/to_signed(1000000000,80);
    if (first_node(G_NODES,b)+i) mod 2=0 then d:=-d;end if;
    return resize(unsigned(shift_left(to_signed(1,80),32)+d),64);
  end;
  function owner(node:natural)return natural is
  begin
    for b in 0 to 2 loop
      if node>=first_node(G_NODES,b) and node<first_node(G_NODES,b)+population(G_NODES,b) then return b;end if;
    end loop;
    assert false report "No instantiated owner for sampled node" severity failure;return 0;
  end;
  function physical_hops(node:natural)return natural is
    variable crossings:natural:=0;
  begin
    for p in 1 to node loop if owner(p)/=owner(p-1) then crossings:=crossings+1;end if;end loop;
    return crossings;
  end;
  function bit_number(value:std_logic)return natural is
  begin if value='1' then return 1;else return 0;end if;end;
begin
  assert (to_unsigned(G_JITTER_MASK,9) and to_unsigned(G_JITTER_MASK+1,9))=0
    report "Jitter mask must be zero or 2**m-1" severity failure;
  process begin
    if G_CAPACITY_CSV then
      report "PTP_CAP_HEADER,version,sample_index,sim_time_ps,capacity,nodes,board,local_slot,node_id,parent_board,parent_local_slot,hops,physical_hops,internal_hops,logical_q48_16,anchor_logical_q48_16,truth_error_q48_16,adjacent_truth_error_q48_16,correction_q48_16,estimated_theta_q48_16,estimated_delay_q48_16,accepted_age_ticks,accepted_count,rejected_count,dropped_count,running,locked,holdover,error,drift_ppb,logical_step_q32_32,jitter_mask,seed,asymmetry,phase_ps" severity note;
    end if;
    wait;
  end process;
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
        to_unsigned(G_JITTER_MASK,8),to_unsigned(G_SEED+b,32),to_unsigned(G_DROP_EVERY,16),1000,2,to_unsigned(0,64),64,
        lrx(b),rrx(b),lrk(b),rrk(b),lrv(b),lrl(b),rrv(b),rrl(b),
        ld(b),rd(b),lk(b),rk(b),lv(b),ll(b),rv(b),rl(b),lready(b),rready(b),raw(b),
        times(b),corrections(b),delays(b),theta(b),ages(b),accepted(b),rejected(b),open,open,open,open,
        running(b),locked(b),holdover(b),errors(b),pulses(b),open,open,idle(b),overflow(b),dropped(b));
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
    variable e,adjacent:signed(63 downto 0);variable n,parent_board,parent_slot,physical:natural;
    variable drift_ppb:integer;
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
        if nominal mod G_SAMPLE_SPACING=0 then
          for b in 0 to 2 loop for i in 0 to population(G_NODES,b)-1 loop
            n:=first_node(G_NODES,b)+i;e:=signed(times(b)(i))-signed(times(0)(0));
            report "PTP_CSV,"&integer'image(ticks)&","&integer'image(n)&","&to_hstring(times(b)(i))&","&to_hstring(e)&","&to_hstring(corrections(b)(i))&","&to_hstring(theta(b)(i))&","&to_hstring(delays(b)(i)) severity note;
            if G_CAPACITY_CSV then
              parent_board:=0;parent_slot:=0;adjacent:=(others=>'0');
              if n>0 then
                parent_board:=owner(n-1);parent_slot:=n-1-first_node(G_NODES,parent_board);
                adjacent:=signed(times(b)(i))-signed(times(parent_board)(parent_slot));
              end if;
              physical:=physical_hops(n);drift_ppb:=G_DRIFT;if n mod 2=0 then drift_ppb:=-G_DRIFT;end if;
              -- Sampling is always at an integer-nanosecond A edge +1 ns.
              -- Append 000 rather than converting millisecond times to a
              -- 32-bit integer number of picoseconds (which would overflow).
              report "PTP_CAP_CSV,1,"&integer'image(nominal/G_SAMPLE_SPACING)&","&integer'image(now/1 ns)&"000,"&
                integer'image(K)&","&integer'image(G_NODES)&","&integer'image(b)&","&integer'image(i)&","&integer'image(n)&","&
                integer'image(parent_board)&","&integer'image(parent_slot)&","&integer'image(n)&","&integer'image(physical)&","&integer'image(n-physical)&","&
                to_hstring(times(b)(i))&","&to_hstring(times(0)(0))&","&to_hstring(e)&","&to_hstring(adjacent)&","&
                to_hstring(corrections(b)(i))&","&to_hstring(theta(b)(i))&","&to_hstring(delays(b)(i))&","&to_hstring(ages(b)(i))&","&
                to_hstring(accepted(b)(i))&","&to_hstring(rejected(b)(i))&","&to_hstring(dropped(b)(i))&","&
                integer'image(bit_number(running(b)(i)))&","&integer'image(bit_number(locked(b)(i)))&","&integer'image(bit_number(holdover(b)(i)))&","&integer'image(bit_number(errors(b)(i)))&","&
                integer'image(drift_ppb)&","&to_hstring(std_logic_vector(step(b,i)))&","&integer'image(G_JITTER_MASK)&","&integer'image(G_SEED+b)&","&
                integer'image(boolean'pos(G_ASYMMETRY))&","&integer'image(phase(b)/1 ps) severity note;
            end if;
            if G_DRIFT=0 and not G_PHASED and G_JITTER_MASK=0 and G_DROP_EVERY=0 then
              if G_ASYMMETRY then
                assert abs(e+to_signed(n*65536,64))<=to_signed(G_NODES*65536/2,64) report "Asymmetry sign or accumulated bias is wrong" severity failure;
              else assert abs(e)<=to_signed(G_NODES*65536/2,64) report "Symmetric links impose an error slope" severity failure;end if;
            end if;
          end loop;end loop;
        end if;
        if nominal=G_NOMINAL_SAMPLES*G_SAMPLE_SPACING then
          assert locked(0)(0)='1' report "Anchor lost lock" severity failure;
          report "PASS PTP chain N="&integer'image(G_NODES)&" acquisition="&integer'image(first_running)&" independent-time samples="&integer'image(G_NOMINAL_SAMPLES) severity note;stop;
        end if;
      end if;
    end if;
    assert ticks<500000 report "PTP chain acquisition timeout" severity failure;
  end process;
end;
