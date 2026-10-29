library ieee;use ieee.std_logic_1164.all;use ieee.numeric_std.all;use std.env.all;
use work.ptp_emulation_pkg.all;
entity tb_ptp_runtime_chain is
  generic(G_CAPACITY:positive:=4;G_INITIAL_NODES:positive:=10;
    G_REDUCED_NODES:positive:=6;G_PHASED:boolean:=false);
end;
architecture test of tb_ptp_runtime_chain is
  signal clk:std_logic_vector(0 to 2):=(others=>'0');signal rst:std_logic:='1';
  signal address:unsigned(15 downto 0):=(others=>'0');signal wd:std_logic_vector(63 downto 0):=(others=>'0');
  signal wr,commit,start,stop_req,snapshot,ack:std_logic:='0';
  signal ld,rd,lrx,rrx:words16_t(0 to 2);signal lk,rk,lrk,rrk:keeps_t(0 to 2);
  signal lv,rv,ll,rl,lready,rready,lrv,rrv,lrl,rrl,ref,pin,apply:std_logic_vector(0 to 2):=(others=>'0');
  signal status:audits_t(0 to 2);signal obs,cid,read_data:words64_t(0 to 2);
  signal selected:words16_t(0 to 2):=(others=>(others=>'0'));
  constant C_PAGE_WORDS:positive:=8+16*G_CAPACITY;
  type pages_t is array(0 to 2) of words64_t(0 to C_PAGE_WORDS-1);
  type event_pages_t is array(0 to 2) of words64_t(0 to 127);
  type counts_t is array(0 to 2) of natural range 0 to 32;
  function phase(b:natural)return time is
  begin if G_PHASED then return b*3 ns;else return 0 ns;end if;end;
begin
  assert G_CAPACITY>=2 and G_INITIAL_NODES<=3*G_CAPACITY and G_INITIAL_NODES>G_REDUCED_NODES and G_REDUCED_NODES>=3
    report "Runtime capacity test needs a valid shrinking population" severity failure;
  boards:for b in 0 to 2 generate
    signal board_start:std_logic;
  begin
    process begin wait for phase(b);loop clk(b)<=not clk(b);wait for 8 ns;end loop;end process;
    board_start<=start when b=0 else '0';
    u:entity work.ptp_emulation_system generic map(G_CAPACITY,3*G_CAPACITY,5000)
      port map(clk(b),rst,'1',address,wd,wr,commit,board_start,stop_req,to_unsigned(b,2),unsigned(selected(b)),apply(b),'1',snapshot,ack,
        read_data(b),status(b),obs(b),cid(b),ref(b),pin(b),lrx(b),rrx(b),lrk(b),rrk(b),lrv(b),lrl(b),rrv(b),rrl(b),
        ld(b),rd(b),lk(b),rk(b),lv(b),ll(b),rv(b),rl(b),lready(b),rready(b));
    f:entity work.physical_link_model generic map(G_DELAY=>160 ns,G_PHASE=>b*19,G_DEPTH=>256)
      port map(clk(b),clk((b+1) mod 3),rst,rd(b),rk(b),rv(b),rl(b),rready(b),lrx((b+1) mod 3),lrk((b+1) mod 3),lrv((b+1) mod 3),lrl((b+1) mod 3));
    r:entity work.physical_link_model generic map(G_DELAY=>160 ns,G_PHASE=>b*29,G_DEPTH=>256)
      port map(clk((b+1) mod 3),clk(b),rst,ld((b+1) mod 3),lk((b+1) mod 3),lv((b+1) mod 3),ll((b+1) mod 3),lready((b+1) mod 3),rrx(b),rrk(b),rrv(b),rrl(b));
  end generate;
  process
    variable previous_raw:unsigned(55 downto 0);
    variable stopped_misses:words32_t(0 to 2);
    variable page:pages_t;variable events:event_pages_t;variable retained:counts_t;
    variable max_retained,event_node:natural;variable good:boolean;
    procedure tick(n:positive:=1) is
    begin for i in 1 to n loop wait until falling_edge(clk(0));end loop;end;
    procedure check_error is
    begin
      for b in 0 to 2 loop assert status(b)(6)='0' report "Runtime capacity firmware error" severity failure;end loop;
      assert ref(1)='0' and ref(2)='0' report "Follower drove the reference GPIO" severity failure;
    end;
    procedure word(a:natural;v:std_logic_vector(63 downto 0)) is
    begin address<=to_unsigned(a,16);wd<=v;tick;wr<='1';tick;wr<='0';tick;end;
    procedure read_word(a:natural) is
    begin address<=to_unsigned(a,16);tick(3);check_error;end;
    procedure configure(n:natural;duration:natural:=0) is
    begin
      word(0,std_logic_vector(to_unsigned(n,64)));word(4,x"0000000000000055");
      word(1,x"00000002000003E8");word(6,x"000003E800000001");word(7,std_logic_vector(to_unsigned(duration,64)));
      commit<='1';tick;commit<='0';tick(8);
      for b in 0 to 2 loop
        assert status(b)(1)='0' and status(b)(0)='1' and cid(b)=x"0000000000000055"
          report "Runtime capacity configuration rejected" severity failure;
        assert unsigned(status(b)(31 downto 16))=G_CAPACITY and unsigned(status(b)(47 downto 32))=n
          and unsigned(status(b)(63 downto 48))=first_node(n,b)
          report "Runtime capacity ownership metadata wrong" severity failure;
      end loop;
    end;
    procedure select_local(n:natural;last_slot:boolean) is
      variable wanted:natural;
    begin
      for b in 0 to 2 loop
        wanted:=first_node(n,b);if last_slot then wanted:=wanted+population(n,b)-1;end if;
        selected(b)<=std_logic_vector(to_unsigned(wanted,16));
      end loop;
      apply<=(others=>'1');tick;apply<=(others=>'0');
      for i in 1 to 3000 loop
        tick;good:=true;
        for b in 0 to 2 loop
          if obs(b)(17 downto 16)/="01" or obs(b)(15 downto 0)/=selected(b) then good:=false;end if;
        end loop;
        exit when good;assert i<3000 report "Runtime local observer did not commit" severity failure;
      end loop;
    end;
    procedure await_running is
    begin
      start<='1';tick;start<='0';
      for cycles in 1 to 100000 loop
        tick;check_error;good:=true;
        for b in 0 to 2 loop if status(b)(3)='0' or status(b)(4)='0' then good:=false;end if;end loop;
        exit when good;assert cycles<100000 report "Runtime anchor-only START did not acquire" severity failure;
      end loop;
    end;
    procedure await_frozen is
    begin
      for cycles in 1 to 10000 loop
        tick;check_error;good:=true;
        for b in 0 to 2 loop if status(b)(7)='0' then good:=false;end if;end loop;
        exit when good;assert cycles<10000 report "Runtime page did not freeze" severity failure;
      end loop;
    end;
    procedure await_idle is
    begin
      for cycles in 1 to 70000 loop
        tick;check_error;good:=true;
        for b in 0 to 2 loop if status(b)(2)='0' then good:=false;end if;end loop;
        exit when good;assert cycles<70000 report "Runtime STOP did not drain" severity failure;
      end loop;
    end;
  begin
    tick(4);rst<='0';tick(4);configure(G_INITIAL_NODES);
    select_local(G_INITIAL_NODES,false);select_local(G_INITIAL_NODES,true);await_running;await_frozen;
    -- A foreign selection retains the last active local slot on each card.
    for b in 0 to 2 loop selected(b)<=std_logic_vector(to_unsigned(first_node(G_INITIAL_NODES,(b+1) mod 3),16));end loop;
    apply<=(others=>'1');tick;apply<=(others=>'0');tick(8);
    for b in 0 to 2 loop
      assert obs(b)(17 downto 16)="11" and unsigned(obs(b)(15 downto 0))=first_node(G_INITIAL_NODES,b)+population(G_INITIAL_NODES,b)-1
        report "Foreign observer selection changed local ownership" severity failure;
    end loop;
    select_local(G_INITIAL_NODES,true);
    for j in 0 to C_PAGE_WORDS-1 loop
      read_word(32768+j);for b in 0 to 2 loop page(b)(j):=read_data(b);end loop;tick(4);
    end loop;
    max_retained:=0;
    for b in 0 to 2 loop
      assert page(b)(0)=x"5054504500010001" and page(b)(1)=x"0000000000000055"
        and unsigned(page(b)(4)(15 downto 0))=first_node(G_INITIAL_NODES,b)
        and unsigned(page(b)(6)(31 downto 0))=population(G_INITIAL_NODES,b)
        report "Runtime frozen page has wrong header/ownership" severity failure;
      retained(b):=to_integer(unsigned(page(b)(6)(63 downto 32)));
      assert retained(b)=to_integer(unsigned(status(b)(175 downto 160)))
        report "Runtime atomic event count differs from page header" severity failure;
      if retained(b)>max_retained then max_retained:=retained(b);end if;
    end loop;
    assert max_retained>0 report "Runtime journal stability coverage retained no events" severity failure;
    for j in 0 to 4*max_retained-1 loop
      read_word(36864+j);
      for b in 0 to 2 loop if j<4*retained(b) then
        events(b)(j):=read_data(b);
        if j mod 4=3 then
          event_node:=to_integer(unsigned(read_data(b)(11 downto 0))&unsigned(events(b)(j-1)(63 downto 60)));
          assert read_data(b)(63)='1' and read_data(b)(12)='1'
            and event_node>=first_node(G_INITIAL_NODES,b) and event_node<first_node(G_INITIAL_NODES,b)+population(G_INITIAL_NODES,b)
            report "Runtime retained audit has invalid local/global ID" severity failure;
        end if;
      end if;end loop;tick(4);
    end loop;
    tick(14000);check_error;
    for b in 0 to 2 loop
      assert status(b)(3)='1' and status(b)(4)='1' and status(b)(7)='1'
        report "Runtime frozen collection suspended PTP" severity failure;
      assert unsigned(status(b)(127 downto 96))>0 and unsigned(status(b)(159 downto 128))>0
        report "Runtime missed snapshots or discarded events not counted" severity failure;
    end loop;
    for j in 0 to C_PAGE_WORDS-1 loop
      read_word(32768+j);
      for b in 0 to 2 loop assert read_data(b)=page(b)(j) report "Runtime page changed before ACK" severity failure;end loop;
    end loop;
    for j in 0 to 4*max_retained-1 loop
      read_word(36864+j);
      for b in 0 to 2 loop if j<4*retained(b) then
        assert read_data(b)=events(b)(j) report "Runtime event changed before ACK" severity failure;
      end if;end loop;tick(4);
    end loop;
    ack<='1';tick;ack<='0';tick(8);await_frozen;
    for i in 0 to G_CAPACITY-1 loop
      read_word(32781+16*i);
      for b in 0 to 2 loop
        if i<population(G_INITIAL_NODES,b) and first_node(G_INITIAL_NODES,b)+i>0 then
          assert unsigned(read_data(b)(63 downto 32))>unsigned(page(b)(13+16*i)(63 downto 32))
            report "Runtime frozen collection suspended maintenance of an active slot" severity failure;
        end if;
      end loop;
    end loop;
    previous_raw:=unsigned(status(0)(231 downto 176));stop_req<='1';tick;stop_req<='0';await_idle;
    configure(G_REDUCED_NODES,20000);
    assert unsigned(status(0)(231 downto 176))>previous_raw report "Runtime reconfiguration reset raw time" severity failure;
    for b in 0 to 2 loop assert obs(b)(16)='0' report "Runtime reconfiguration left observer enabled" severity failure;end loop;
    selected(2)<=std_logic_vector(to_unsigned(G_INITIAL_NODES-1,16));apply(2)<='1';tick;apply(2)<='0';tick(8);
    assert obs(2)(16)='0' and obs(2)(17)='1' report "Shrunken population accepted old observer ID" severity failure;
    select_local(G_REDUCED_NODES,false);select_local(G_REDUCED_NODES,true);await_running;await_frozen;
    for i in 0 to G_CAPACITY-1 loop
      read_word(32784+16*i);
      for b in 0 to 2 loop if i>=population(G_REDUCED_NODES,b) then
        assert read_data(b)(35 downto 32)="0000" report "Inactive slot participates after population shrink" severity failure;
      end if;end loop;
      read_word(32781+16*i);
      for b in 0 to 2 loop if i>=population(G_REDUCED_NODES,b) then
        assert read_data(b)=x"0000000000000000" report "Inactive slot accepted/rejected transactions after shrink" severity failure;
      end if;end loop;
    end loop;
    tick(22000);await_idle;
    for b in 0 to 2 loop
      assert status(b)(3)='0' and status(b)(10)='1' and status(b)(11)='0' and status(b)(12)='1'
        report "Runtime timed run did not stop cleanly" severity failure;
      stopped_misses(b):=status(b)(127 downto 96);
    end loop;
    tick(2500);check_error;
    for b in 0 to 2 loop assert stopped_misses(b)=status(b)(127 downto 96) report "Late frame restarted runtime collection after timed STOP" severity failure;end loop;
    report "PASS runtime capacity K="&integer'image(G_CAPACITY)&" N="&integer'image(G_INITIAL_NODES)&" to "&integer'image(G_REDUCED_NODES)&
      ": anchor-only START, all-slot maintenance, observer ownership, frozen page/events, inactive slots, STOP/drain/timed rearm" severity note;stop;
  end process;
end;
