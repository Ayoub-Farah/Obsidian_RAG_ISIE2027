library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;
use work.benchmark_pkg.all;
use work.physical_pkg.all;
entity tb_physical_node is end;
architecture test of tb_physical_node is
  type times_t is array(0 to 2) of ticks_t;
  type sums_t is array(0 to 2) of summary_t;
  type hops_t is array(0 to 2) of unsigned(15 downto 0);
  type ids_t is array(0 to 2) of unsigned(1 downto 0);
  signal clk:std_logic:='0';signal rst,start:std_logic:='1';
  signal raw:ticks_t:=(others=>'0');signal cfg:config_t:=C_DEFAULT_CONFIG;
  signal trial:std_logic_vector(31 downto 0):=(others=>'0');
  signal td,rd:word_array_t(0 to 2);signal tk,rk:keep_array_t(0 to 2);
  signal tv,tl,tr,rv,rl,idle,fault,removed,bad:std_logic_vector(0 to 2);
  signal origins:ids_t;signal hops:hops_t;signal sums:sums_t;
  signal seen:std_logic_vector(0 to 2):=(others=>'0');
  signal pauses:boolean:=false;signal ticks:natural:=0;
  signal tx_first,rx_last:times_t:=(others=>(others=>'0'));
  signal cutthrough_seen:std_logic_vector(0 to 2):=(others=>'0');
  signal tx_inframe,rx_inframe:std_logic_vector(0 to 2):=(others=>'0');
begin
  clk<=not clk after 8 ns;
  process(clk) begin if rising_edge(clk) then raw<=raw+1;ticks<=ticks+1;end if;end process;
  boards:for b in 0 to 2 generate
    constant PREV:natural:=(b+2) mod 3;
  begin
    dut:entity work.physical_node
      port map(clk_i=>clk,rst_i=>rst,raw_i=>raw,config_i=>cfg,board_i=>to_unsigned(b,2),
        start_i=>start,run_i=>x"00000001",trial_i=>trial,
        rx_data_i=>rd(b),rx_keep_i=>rk(b),rx_valid_i=>rv(b),rx_last_i=>rl(b),rx_stamp_i=>raw,
        tx_data_o=>td(b),tx_keep_o=>tk(b),tx_valid_o=>tv(b),tx_last_o=>tl(b),tx_ready_i=>tr(b),
        idle_o=>idle(b),fault_o=>fault(b),removed_o=>removed(b),removed_origin_o=>origins(b),
        removed_hops_o=>hops(b),removed_bad_o=>bad(b),event_tx_o=>open,event_rx_o=>open,
        event_tx_valid_o=>open,event_rx_valid_o=>open,summary_o=>sums(b));
    link:entity work.virtual_neighbor_link generic map(G_LATENCY_CYCLES=>37,G_FIFO_WORDS=>8192,G_CC_PHASE=>b*91)
      port map(clk,rst,td(PREV),tk(PREV),tv(PREV),tl(PREV),tr(PREV),rd(b),rk(b),rv(b),rl(b),open,open);
  end generate;
  monitor:process(clk)
  begin if rising_edge(clk) then
    if rst='1' or start='1' then seen<=(others=>'0');cutthrough_seen<=(others=>'0');tx_inframe<=(others=>'0');rx_inframe<=(others=>'0');
    else
      for b in 0 to 2 loop
        assert fault(b)='0' report "Physical node fault board "&integer'image(b) severity failure;
        if removed(b)='1' then
          assert seen(b)='0' report "Duplicate removal" severity failure;
          assert bad(b)='0' report "CRC/pattern failed board "&integer'image(b) severity failure;
          if cfg_mode(cfg)=C_RAG then
            assert to_integer(hops(b))=cfg_hops(cfg) report "Wrong physical hop count" severity failure;
            assert to_integer(origins(b))=(b+3-(cfg_hops(cfg) mod 3)) mod 3 report "Wrong removal board" severity failure;
          else assert b=0 and hops(b)=3 report "CT removed at wrong board" severity failure;end if;
          seen(b)<='1';
        end if;
        if rv(b)='1' then
          rx_inframe(b)<='1';if rl(b)='1' then rx_inframe(b)<='0';rx_last(b)<=raw;end if;
        end if;
        if tv(b)='1' and tr(b)='1' then
          if tx_inframe(b)='0' then
            tx_first(b)<=raw;
            if rx_inframe(b)='1' then cutthrough_seen(b)<='1';end if;
          end if;
          tx_inframe(b)<='1';if tl(b)='1' then tx_inframe(b)<='0';end if;
        end if;
      end loop;
    end if;
  end if;end process;
  process
    procedure campaign(mode,p,s,h:natural) is
      variable done:boolean;
    begin
      cfg<=make_config(1,p,s,h,mode,to_unsigned(1,32),to_unsigned(6250,32));
      trial<=std_logic_vector(unsigned(trial)+1);wait until falling_edge(clk);start<='1';
      wait until falling_edge(clk);start<='0';done:=false;
      for k in 0 to 12000000 loop
        wait until rising_edge(clk);wait for 1 ns;
        done:=idle="111" and ((mode=C_CT and seen(0)='1') or (mode=C_RAG and seen="111"));
        exit when done;
      end loop;
      assert done report "Physical campaign timeout mode="&integer'image(mode)&" H="&integer'image(h) severity failure;
      if mode=C_RAG then
        for b in 0 to 2 loop
          assert unsigned(sums(b)(847 downto 784))=h and unsigned(sums(b)(783 downto 720))=h-1
            report "H did not correspond to the actual physical RX/relay counts" severity failure;
        end loop;
      end if;
      if mode=C_CT and p>=64 then
        assert cutthrough_seen(1)='1' and cutthrough_seen(2)='1' report "CT became store-and-forward" severity failure;
        assert unsigned(sums(0)(591 downto 528))=rx_last(0) report "RX last timestamp shifted" severity failure;
      end if;
      report "PHYSICAL_NODE_PASS mode="&integer'image(mode)&" P="&integer'image(p)&" S="&integer'image(s)&" H="&integer'image(h);
      wait for 128 ns;
    end procedure;
  begin
    start<='0';wait for 128 ns;wait until falling_edge(clk);rst<='0';
    campaign(C_CT,4096,6,2);
    campaign(C_RAG,1,6,1);campaign(C_RAG,257,6,2);campaign(C_RAG,4096,6,3);
    campaign(C_RAG,4095,6,4);campaign(C_RAG,7,6,29);campaign(C_RAG,1,6,65535);
    campaign(C_CT,4095,1365,2);campaign(C_CT,3,1,2);
    report "PASS tb_physical_node";stop;wait;
  end process;
end;
