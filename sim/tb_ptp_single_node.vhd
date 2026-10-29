-- Three physical cards, one complete PTP engine per card. This exercises the
-- register/JTAG contract as well as PTP; it is not an Aurora IP simulation.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;
use work.ptp_emulation_pkg.all;

entity tb_ptp_single_node is end;

architecture test of tb_ptp_single_node is
  type page_set_t is array(0 to 2) of words64_t(0 to 23);
  type event_set_t is array(0 to 2) of words64_t(0 to 127);
  type counts_t is array(0 to 2) of natural range 0 to 32;
  signal clk : std_logic_vector(0 to 2) := (others=>'0');
  signal rst : std_logic := '1';
  signal address : unsigned(15 downto 0) := (others=>'0');
  signal wd : std_logic_vector(63 downto 0) := (others=>'0');
  signal wr,commit,stop_req,snapshot,ack : std_logic := '0';
  signal start,write_board,apply : std_logic_vector(0 to 2) := (others=>'0');
  signal selected : words16_t(0 to 2) := (others=>(others=>'0'));
  signal ld,rd,lrx,rrx : words16_t(0 to 2);
  signal lk,rk,lrk,rrk : keeps_t(0 to 2);
  signal lv,rv,ll,rl,lready,rready,lrv,rrv,lrl,rrl,ref,pin : std_logic_vector(0 to 2);
  signal status : audits_t(0 to 2);
  signal obs,cid,read_data : words64_t(0 to 2);
begin
  boards: for b in 0 to 2 generate
    -- Same 62.5 MHz frequency, different phase at each physical endpoint.
    process begin
      wait for b*3 ns;
      loop clk(b)<=not clk(b);wait for 8 ns;end loop;
    end process;
    u: entity work.ptp_emulation_system generic map(1,3,5000)
      port map(clk(b),rst,'1',address,wd,wr and write_board(b),commit,start(b),stop_req,
        to_unsigned(b,2),unsigned(selected(b)),apply(b),'1',snapshot,ack,
        read_data(b),status(b),obs(b),cid(b),ref(b),pin(b),
        lrx(b),rrx(b),lrk(b),rrk(b),lrv(b),lrl(b),rrv(b),rrl(b),
        ld(b),rd(b),lk(b),rk(b),lv(b),ll(b),rv(b),rl(b),lready(b),rready(b));
    forward_physical: entity work.physical_link_model
      generic map(G_DELAY=>160 ns,G_PHASE=>b*19,G_DEPTH=>256)
      port map(clk(b),clk((b+1) mod 3),rst,rd(b),rk(b),rv(b),rl(b),rready(b),
        lrx((b+1) mod 3),lrk((b+1) mod 3),lrv((b+1) mod 3),lrl((b+1) mod 3));
    reverse_physical: entity work.physical_link_model
      generic map(G_DELAY=>160 ns,G_PHASE=>b*29,G_DEPTH=>256)
      port map(clk((b+1) mod 3),clk(b),rst,ld((b+1) mod 3),lk((b+1) mod 3),
        lv((b+1) mod 3),ll((b+1) mod 3),lready((b+1) mod 3),
        rrx(b),rrk(b),rrv(b),rrl(b));
  end generate;

  -- COMMIT, STOP and rearm must never reset physical time. The reference pin
  -- belongs only to A even though all boards contain a local slot zero.
  process
    variable previous : words64_t(0 to 2) := (others=>(others=>'0'));
    variable ticks : natural := 0;
  begin
    wait until rising_edge(clk(0));wait for 1 ns;
    ticks:=ticks+1;
    if rst='0' then
      for b in 0 to 2 loop
        assert unsigned(status(b)(231 downto 176))>=unsigned(previous(b)(55 downto 0))
          report "K1 physical raw time moved backwards" severity failure;
        previous(b)(55 downto 0):=status(b)(231 downto 176);
        assert status(b)(6)='0' report "K1 firmware error or boundary FIFO overflow" severity failure;
      end loop;
      assert ref(1)='0' and ref(2)='0' report "K1 reference pin driven by a follower" severity failure;
    end if;
    assert ticks<250000 report "K1 test watchdog" severity failure;
  end process;

  process
    variable frozen_page : page_set_t;
    variable frozen_events : event_set_t;
    variable retained : counts_t;
    variable max_retained : natural;
    variable frozen_misses,stopped_misses : words32_t(0 to 2);
    variable previous_raw : unsigned(55 downto 0);
    variable good : boolean;

    procedure tick(n:positive:=1) is
    begin for i in 1 to n loop wait until falling_edge(clk(0));end loop;end;

    procedure word(a:natural;v:std_logic_vector(63 downto 0);owner:integer:=-1) is
    begin
      address<=to_unsigned(a,16);wd<=v;write_board<=(others=>'0');
      if owner<0 then write_board<=(others=>'1');else write_board(owner)<='1';end if;
      tick;wr<='1';tick;wr<='0';tick;
    end;

    procedure read_word(a:natural) is
    begin
      address<=to_unsigned(a,16);
      -- Allows synchronous event RAM and independently phased board clocks.
      tick(3);
    end;

    procedure configure(run_id:positive;duration:natural:=0) is
    begin
      word(0,x"0000000000000003");word(1,x"00000002000003E8");
      word(2,std_logic_vector(shift_left(to_unsigned(5000,64),16)));
      word(4,x"0000000000000055");word(5,std_logic_vector(to_unsigned(run_id,64)));
      word(6,x"000007D000000001");word(7,std_logic_vector(to_unsigned(duration,64)));
      -- Runtime steps represent 0, +2000 and -2000 ppb, precomputed by host.
      word(16,x"0000000100000000",0);word(16,x"000000010000218D",1);
      word(16,x"00000000FFFFDE73",2);
      word(17,std_logic_vector(to_signed(11*65536,64)),1);
      word(17,std_logic_vector(to_signed(-7*65536,64)),2);
      commit<='1';tick;commit<='0';tick(8);
      for b in 0 to 2 loop
        assert status(b)(1)='0' and status(b)(0)='1' and cid(b)=x"0000000000000055"
          report "K1 coherent configuration rejected" severity failure;
        assert unsigned(status(b)(31 downto 16))=1 and unsigned(status(b)(47 downto 32))=3
          and unsigned(status(b)(63 downto 48))=b
          report "K1 capacity, population or local ownership wrong" severity failure;
      end loop;
    end;

    procedure select_local is
    begin
      for b in 0 to 2 loop selected(b)<=std_logic_vector(to_unsigned(b,16));end loop;
      apply<=(others=>'1');tick;apply<=(others=>'0');tick(12);
      for b in 0 to 2 loop
        assert obs(b)(17 downto 16)="01" and unsigned(obs(b)(15 downto 0))=b
          report "K1 local observation selection failed" severity failure;
      end loop;
    end;

    procedure await_running is
    begin
      -- A alone starts the ring after all three COMMITs.
      start(0)<='1';tick;start(0)<='0';
      for i in 1 to 100000 loop
        tick;good:=true;
        for b in 0 to 2 loop
          if status(b)(3)='0' or status(b)(4)='0' then good:=false;end if;
        end loop;
        exit when good;
        assert i<100000 report "K1 anchor-only START did not acquire" severity failure;
      end loop;
    end;

    procedure await_frozen is
    begin
      for i in 1 to 10000 loop
        tick;good:=true;
        for b in 0 to 2 loop if status(b)(7)='0' then good:=false;end if;end loop;
        exit when good;
        assert i<10000 report "K1 snapshot/event writer did not freeze" severity failure;
      end loop;
    end;

    procedure await_idle is
    begin
      for i in 1 to 70000 loop
        tick;good:=true;
        for b in 0 to 2 loop if status(b)(2)='0' then good:=false;end if;end loop;
        exit when good;
        assert i<70000 report "K1 STOP failed to drain" severity failure;
      end loop;
    end;
  begin
    tick(4);rst<='0';tick(4);configure(1);select_local;await_running;await_frozen;
    for b in 0 to 2 loop frozen_misses(b):=status(b)(127 downto 96);end loop;
    for j in 0 to 23 loop
      read_word(32768+j);
      for b in 0 to 2 loop frozen_page(b)(j):=read_data(b);end loop;
      tick(8); -- Slow host access, with PTP continuing underneath.
    end loop;
    max_retained:=0;
    for b in 0 to 2 loop
      assert frozen_page(b)(0)=x"5054504500010001" and frozen_page(b)(1)=x"0000000000000055"
        and frozen_page(b)(2)=x"0000000000000001"
        report "K1 snapshot header corrupt" severity failure;
      retained(b):=to_integer(unsigned(frozen_page(b)(6)(63 downto 32)));
      if retained(b)>max_retained then max_retained:=retained(b);end if;
      assert unsigned(frozen_page(b)(6)(31 downto 0))=1
        and unsigned(frozen_page(b)(4)(15 downto 0))=b
        report "K1 page describes wrong local module" severity failure;
    end loop;
    assert max_retained>0 report "K1 frozen-event stability test retained no events" severity failure;
    for j in 0 to 4*max_retained-1 loop
      read_word(36864+j);
      for b in 0 to 2 loop
        if j<4*retained(b) then
          frozen_events(b)(j):=read_data(b);
          if j mod 4=3 then
            assert read_data(b)(63)='1' and read_data(b)(12)='1'
              and (unsigned(read_data(b)(11 downto 0))&unsigned(frozen_events(b)(j-1)(63 downto 60)))=b
              report "K1 retained event lost validity or global module ID" severity failure;
          end if;
        end if;
      end loop;
      tick(8);
    end loop;
    tick(12000);
    -- Invalid selection must retain this card's sole observation, never borrow
    -- another card's module. No PTP reset or configuration operation is involved.
    for b in 0 to 2 loop selected(b)<=std_logic_vector(to_unsigned((b+1) mod 3,16));end loop;
    apply<=(others=>'1');tick;apply<=(others=>'0');tick(8);
    for b in 0 to 2 loop
      assert obs(b)(17 downto 16)="11" and unsigned(obs(b)(15 downto 0))=b
        report "K1 foreign module selection changed local ownership" severity failure;
      assert status(b)(3)='1' and status(b)(4)='1' and status(b)(7)='1'
        report "K1 frozen snapshots suspended PTP or lost lock" severity failure;
      assert unsigned(status(b)(127 downto 96))>unsigned(frozen_misses(b))
        report "K1 discarded periodic snapshots were not counted" severity failure;
      assert unsigned(status(b)(159 downto 128))>0
        report "K1 events discarded during slow collection were not counted" severity failure;
    end loop;
    for j in 0 to 23 loop
      read_word(32768+j);
      for b in 0 to 2 loop
        assert read_data(b)=frozen_page(b)(j) report "K1 page changed before ACK" severity failure;
      end loop;
    end loop;
    for j in 0 to 4*max_retained-1 loop
      read_word(36864+j);
      for b in 0 to 2 loop
        if j<4*retained(b) then
          assert read_data(b)=frozen_events(b)(j) report "K1 event RAM changed before ACK" severity failure;
        end if;
      end loop;
      tick(8);
    end loop;
    select_local;
    ack<='1';tick;ack<='0';tick(8);await_frozen;
    read_word(32781);
    for b in 1 to 2 loop
      assert unsigned(read_data(b)(63 downto 32))>unsigned(frozen_page(b)(13)(63 downto 32))
        report "K1 maintenance estimates did not advance during frozen JTAG reads" severity failure;
    end loop;

    previous_raw:=unsigned(status(0)(231 downto 176));
    stop_req<='1';tick;stop_req<='0';await_idle;
    -- Reconfigure the same physical ring after a drained STOP; no raw reset.
    configure(2,20000);
    assert unsigned(status(0)(231 downto 176))>previous_raw report "K1 rearm reset raw time" severity failure;
    select_local;await_running;tick(22000);await_idle;
    for b in 0 to 2 loop
      assert status(b)(3)='0' and status(b)(10)='1' and status(b)(11)='0' and status(b)(12)='1'
        report "K1 finite run did not retain nominal evidence and STOP latch" severity failure;
      stopped_misses(b):=status(b)(127 downto 96);
    end loop;
    tick(2500);
    for b in 0 to 2 loop
      assert stopped_misses(b)=status(b)(127 downto 96)
        report "K1 late frames restarted sampling after timed STOP" severity failure;
    end loop;
    report "PASS K1/N3 phased ring, runtime drift/offset, anchor-only START, local observation ownership, frozen pages/events, live maintenance, STOP/drain and timed rearm" severity note;
    stop;
  end process;
end;
