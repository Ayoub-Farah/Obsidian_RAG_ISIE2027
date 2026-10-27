library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;
use work.benchmark_pkg.all;
use work.physical_pkg.all;
entity tb_physical_integrity is generic(G_FAULT:natural:=0);end;
architecture test of tb_physical_integrity is
  type ids_t is array(0 to 2) of unsigned(1 downto 0);
  signal clk:std_logic:='0';signal rst:std_logic:='1';signal start:std_logic:='0';
  signal raw:ticks_t:=(others=>'0');signal cfg:config_t:=make_config(1,257,7,2,C_CT,to_unsigned(1,32),to_unsigned(6250,32));
  signal td,rd,wire_data:word_array_t(0 to 2);signal tk,rk:keep_array_t(0 to 2);
  signal tv,tl,tr,rv,rl,idle,fault,removed,bad:std_logic_vector(0 to 2);
  signal tx_inframe,rx_inframe,cut_seen,wire_done,wire_bad:std_logic_vector(0 to 2):=(others=>'0');
  signal word_index:natural:=0;signal injected:std_logic:='0';
begin
  clk<=not clk after 8 ns;process(clk) begin if rising_edge(clk) then raw<=raw+1;end if;end process;
  process(all)
    variable target:natural;variable d:std_logic_vector(15 downto 0);
  begin
    rd<=wire_data;target:=8191;
    case G_FAULT is when 1=>target:=39;when 2=>target:=200;when 3=>target:=289;when 4=>target:=8;when others=>null;end case;
    if injected='0' and word_index=target/2 then
      d:=wire_data(1);if target mod 2=0 then d(8):=not d(8);else d(0):=not d(0);end if;rd(1)<=d;
    end if;
  end process;
  process(clk) begin if rising_edge(clk) then
    if rst='1' then word_index<=0;injected<='0';
    elsif rv(1)='1' then
      if rl(1)='1' then word_index<=0;injected<='1';else word_index<=word_index+1;end if;
    end if;
  end if;end process;
  boards:for b in 0 to 2 generate
    constant PREV:natural:=(b+2) mod 3;
  begin
    node:entity work.physical_node port map(clk,rst,raw,cfg,to_unsigned(b,2),start,x"00000001",x"00000005",
      rd(b),rk(b),rv(b),rl(b),raw,td(b),tk(b),tv(b),tl(b),tr(b),idle(b),fault(b),removed(b),open,open,bad(b),open,open,open,open,open);
    link:entity work.physical_link_model generic map(G_PHASE=>b*17,G_GAPS=>true)
      port map(clk,clk,rst,td(PREV),tk(PREV),tv(PREV),tl(PREV),tr(PREV),wire_data(b),rk(b),rv(b),rl(b));
    check:process(clk)
      variable c:std_logic_vector(31 downto 0):=x"FFFFFFFF";
      variable previous_data:std_logic_vector(15 downto 0);variable previous_keep:std_logic_vector(1 downto 0);
      variable previous_last:std_logic;variable stalled:boolean:=false;
    begin if rising_edge(clk) then
      if rst='0' then
        if stalled then assert tv(b)='1' and td(b)=previous_data and tk(b)=previous_keep and tl(b)=previous_last report "TX changed under stall" severity failure;end if;
        stalled:=tv(b)='1' and tr(b)='0';previous_data:=td(b);previous_keep:=tk(b);previous_last:=tl(b);
        if rv(b)='1' then rx_inframe(b)<='1';if rl(b)='1' then rx_inframe(b)<='0';end if;end if;
        if tv(b)='1' and tr(b)='1' then
          if tx_inframe(b)='0' then c:=x"FFFFFFFF";if rx_inframe(b)='1' then cut_seen(b)<='1';end if;end if;
          c:=crc32_byte(c,td(b)(15 downto 8));if tk(b)="11" then c:=crc32_byte(c,td(b)(7 downto 0));end if;
          tx_inframe(b)<='1';
          if tl(b)='1' then tx_inframe(b)<='0';wire_done(b)<='1';if c/=x"DEBB20E3" then wire_bad(b)<='1';end if;end if;
        end if;
      end if;
    end if;end process;
  end generate;
  process
    variable done:boolean:=false;
  begin
    wait for 128 ns;wait until falling_edge(clk);rst<='0';start<='1';wait until falling_edge(clk);start<='0';
    for k in 0 to 30000 loop
      wait until rising_edge(clk);wait for 1 ns;
      if G_FAULT=4 then done:=fault(1)='1';else done:=removed(0)='1';end if;
      exit when done;
    end loop;
    assert done report "Integrity test did not complete" severity failure;
    if G_FAULT=4 then assert wire_done(1)='0' report "Invalid header relayed" severity failure;
    else
      assert fault="000" report "Payload/CRC error became an unrecoverable framing fault" severity failure;
      assert wire_done="111" and wire_bad(0)='0' report "Wrong initial CRC or missing relay" severity failure;
      assert cut_seen(1)='1' and cut_seen(2)='1' report "CRC tail checking broke cut-through" severity failure;
      if G_FAULT=0 then assert bad(0)='0' and wire_bad="000" report "Valid frame rejected" severity failure;
      else assert bad(0)='1' and wire_bad(1)='1' and wire_bad(2)='1' report "CRC corruption healed after modification" severity failure;end if;
    end if;
    report "PASS tb_physical_integrity fault="&integer'image(G_FAULT);stop;wait;
  end process;
end;
