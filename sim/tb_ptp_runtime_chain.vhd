library ieee;use ieee.std_logic_1164.all;use ieee.numeric_std.all;use std.env.all;
use work.ptp_emulation_pkg.all;
entity tb_ptp_runtime_chain is end;
architecture test of tb_ptp_runtime_chain is
  signal clk:std_logic:='0';signal rst:std_logic:='1';
  signal address:unsigned(15 downto 0):=(others=>'0');signal wd:std_logic_vector(63 downto 0):=(others=>'0');
  signal wr,commit,start,stop_req,snapshot,ack:std_logic:='0';
  signal ld,rd,lrx,rrx:words16_t(0 to 2);signal lk,rk,lrk,rrk:keeps_t(0 to 2);
  signal lv,rv,ll,rl,lready,rready,lrv,rrv,lrl,rrl,ref,pin,apply:std_logic_vector(0 to 2):=(others=>'0');
  signal status:audits_t(0 to 2);signal obs,cid,read_data:words64_t(0 to 2);
  signal selected:unsigned(15 downto 0):=to_unsigned(9,16);
begin
  clk<=not clk after 8 ns;
  boards:for b in 0 to 2 generate
    signal board_start:std_logic;
  begin
    board_start<=start when b=0 else '0';
    u:entity work.ptp_emulation_system generic map(4,12,5000)
      port map(clk,rst,'1',address,wd,wr,commit,board_start,stop_req,to_unsigned(b,2),selected,apply(b),'1',snapshot,ack,
        read_data(b),status(b),obs(b),cid(b),ref(b),pin(b),lrx(b),rrx(b),lrk(b),rrk(b),lrv(b),lrl(b),rrv(b),rrl(b),
        ld(b),rd(b),lk(b),rk(b),lv(b),ll(b),rv(b),rl(b),lready(b),rready(b));
    f:entity work.physical_link_model generic map(G_DELAY=>160 ns,G_PHASE=>b*19,G_DEPTH=>256)
      port map(clk,clk,rst,rd(b),rk(b),rv(b),rl(b),rready(b),lrx((b+1) mod 3),lrk((b+1) mod 3),lrv((b+1) mod 3),lrl((b+1) mod 3));
    r:entity work.physical_link_model generic map(G_DELAY=>160 ns,G_PHASE=>b*29,G_DEPTH=>256)
      port map(clk,clk,rst,ld((b+1) mod 3),lk((b+1) mod 3),lv((b+1) mod 3),ll((b+1) mod 3),lready((b+1) mod 3),rrx(b),rrk(b),rrv(b),rrl(b));
  end generate;
  process
    variable previous_raw:unsigned(55 downto 0);
    variable stopped_misses:words32_t(0 to 2);
    variable frozen_accepted:words32_t(0 to 2);
    procedure tick is begin wait until falling_edge(clk);end;
    procedure word(a:natural;v:std_logic_vector(63 downto 0)) is
    begin address<=to_unsigned(a,16);wd<=v;tick;wr<='1';tick;wr<='0';tick;end;
    procedure configure(n:natural;duration:natural:=0) is
    begin word(0,std_logic_vector(to_unsigned(n,64)));word(4,x"0000000000000055");
      word(1,x"00000002000003E8");
      word(6,x"000003E800000001");word(7,std_logic_vector(to_unsigned(duration,64)));
      commit<='1';tick;commit<='0';tick;tick;
      for b in 0 to 2 loop assert status(b)(1)='0' and status(b)(0)='1' and cid(b)=x"0000000000000055" severity failure;end loop;
    end;
    procedure await_running is
      variable good:boolean;variable cycles:natural:=0;
    begin
      start<='1';tick;start<='0';
      loop
        tick;good:=true;cycles:=cycles+1;
        for b in 0 to 2 loop
          assert status(b)(6)='0' report "Runtime chain firmware error" severity failure;
          if status(b)(3)='0' then good:=false;end if;
        end loop;
        exit when good;assert cycles<100000 report "Runtime START did not acquire" severity failure;
      end loop;
    end;
  begin
    tick;rst<='0';tick;configure(10);await_running;
    apply(2)<='1';tick;apply(2)<='0';for i in 0 to 8 loop tick;end loop;
    assert obs(2)(16)='1' and obs(2)(15 downto 0)=x"0009" report "M10 selection failed" severity failure;
    address<=to_unsigned(32781,16);tick;
    for b in 0 to 2 loop frozen_accepted(b):=read_data(b)(63 downto 32);end loop;
    for i in 0 to 14000 loop tick;end loop;
    for b in 0 to 2 loop
      assert status(b)(3)='1' and status(b)(4)='1' and status(b)(7)='1' report "Follower did not auto-sample, or snapshot suspended PTP" severity failure;
      assert unsigned(status(b)(127 downto 96))>0 report "Missed follower snapshots were not counted" severity failure;
    end loop;
    ack<='1';tick;ack<='0';for i in 0 to 1100 loop tick;end loop;
    for b in 1 to 2 loop
      assert unsigned(read_data(b)(63 downto 32))>unsigned(frozen_accepted(b)) report "Frozen-page collection suspended PTP maintenance" severity failure;
    end loop;
    previous_raw:=unsigned(status(0)(231 downto 176));stop_req<='1';tick;stop_req<='0';
    for i in 0 to 70000 loop
      tick;exit when status(0)(2)='1' and status(1)(2)='1' and status(2)(2)='1';
      assert i<70000 report "PTP STOP did not drain" severity failure;
    end loop;
    configure(6,20000);assert unsigned(status(0)(231 downto 176))>previous_raw report "Reconfiguration reset raw time" severity failure;
    assert obs(2)(16)='0' report "Population change left an invalid observation enabled" severity failure;
    await_running;
    for i in 0 to 22000 loop tick;end loop;
    for b in 0 to 2 loop
      assert status(b)(2)='1' and status(b)(3)='0' and status(b)(6)='0' and status(b)(10)='1' and status(b)(11)='0' report "Timed run did not stop cleanly on every board" severity failure;
      stopped_misses(b):=status(b)(127 downto 96);
    end loop;
    for i in 0 to 2500 loop tick;end loop;
    for b in 0 to 2 loop assert stopped_misses(b)=status(b)(127 downto 96) report "A late frame restarted collection after timed STOP" severity failure;end loop;
    report "PASS anchor-only START, follower auto-sampling and duration, N=10 to N=6, STOP/drain/rearm, maintenance during frozen snapshots" severity note;stop;
  end process;
end;
