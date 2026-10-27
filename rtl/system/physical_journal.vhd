-- One synchronous 8192x64 BRAM, frozen pages; trace loss never loses a summary.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.physical_pkg.all;
entity physical_journal is
  port(clk_i,rst_i:in std_logic;raw_i:in ticks_t;board_i:in unsigned(1 downto 0);
    config_i:in config_t;
    summary_i:in summary_t;summary_valid_i,freeze_i,ack_i:in std_logic;
    event_a_i,event_b_i:in event_t;event_a_valid_i,event_b_valid_i:in std_logic;
    audit_a_i,audit_b_i:in std_logic_vector(255 downto 0);
    skipped_i:in ticks_t;
    address_i:in unsigned(12 downto 0);data_o:out std_logic_vector(63 downto 0);
    frozen_o,busy_o:out std_logic;summary_count_o:out unsigned(7 downto 0);
    lost_events_o,lost_calibration_o:out unsigned(31 downto 0));
end;
architecture rtl of physical_journal is
  type ram_t is array(0 to 8191) of std_logic_vector(63 downto 0);
  signal ram:ram_t;
  attribute ram_style:string;attribute ram_style of ram:signal is "block";
  type queue_t is array(0 to 7) of std_logic_vector(256 downto 0);
  signal queue:queue_t;
  type holding_t is array(0 to 3) of std_logic_vector(255 downto 0);
  signal holding:holding_t;signal holding_valid:std_logic_vector(3 downto 0):=(others=>'0');
  signal round_robin:natural range 0 to 3:=0;
  signal qr,qw:natural range 0 to 7:=0;signal qu:natural range 0 to 8:=0;
  signal ns:natural range 0 to 128:=0;signal ne:natural range 0 to 1024:=0;signal nc:natural range 0 to 256:=0;
  signal lost,cal_lost:unsigned(31 downto 0):=(others=>'0');
  signal saved:summary_t:=(others=>'0');signal saving,seal,frozen:std_logic:='0';
  signal si:natural range 0 to 31:=0;signal qi:natural range 0 to 3:=0;
  signal meta:natural range 0 to 16:=0;signal page:unsigned(31 downto 0):=(others=>'0');
  signal ram_write:std_logic:='0';signal ram_address:unsigned(12 downto 0):=(others=>'0');
  signal ram_word:std_logic_vector(63 downto 0):=(others=>'0');
  signal previous_ack:std_logic:='0';
  function advance(v:natural) return natural is begin if v=7 then return 0;else return v+1;end if;end;
begin
  frozen_o<=frozen;busy_o<=saving or seal;
  summary_count_o<=to_unsigned(ns,8);lost_events_o<=lost;lost_calibration_o<=cal_lost;
  -- Explicit one-write-port template. Region-specific writes in the scheduler
  -- must not infer several ports and silently spill this RAM into LUTRAM.
  process(clk_i) begin if rising_edge(clk_i) then
    if ram_write='1' then ram(to_integer(ram_address))<=ram_word;end if;
    data_o<=ram(to_integer(address_i));
  end if;end process;
  process(clk_i)
    variable count,wp,rp:natural;variable le,lc:unsigned(31 downto 0);
    variable item:std_logic_vector(256 downto 0);variable w:std_logic_vector(63 downto 0);
    variable hv:std_logic_vector(3 downto 0);variable selected,port_index:integer;
  begin if rising_edge(clk_i) then
    ram_write<='0';
    previous_ack<=ack_i;
    if rst_i='1' then
      ns<=0;ne<=0;nc<=0;lost<=(others=>'0');cal_lost<=(others=>'0');saving<='0';seal<='0';frozen<='0';
      qr<=0;qw<=0;qu<=0;si<=0;qi<=0;meta<=0;page<=(others=>'0');
      holding_valid<=(others=>'0');round_robin<=0;
      previous_ack<='0';
    elsif ack_i='1' and previous_ack='0' and frozen='1' then
      ns<=0;ne<=0;nc<=0;lost<=(others=>'0');cal_lost<=(others=>'0');frozen<='0';seal<='0';meta<=0;
      qr<=0;qw<=0;qu<=0;qi<=0;page<=page+1;
      holding_valid<=(others=>'0');round_robin<=0;
    elsif frozen='0' then
      count:=qu;wp:=qw;rp:=qr;le:=lost;lc:=cal_lost;
      hv:=holding_valid;
      if freeze_i='1' then seal<='1';end if;
      if summary_valid_i='1' then
        assert saving='0' and ns<128 report "Summary journal capacity exceeded" severity failure;
        if saving='0' and ns<128 then saved<=summary_i;saving<='1';si<=0;end if;
      end if;
      if saving='1' then
        ram_write<='1';ram_address<=to_unsigned(ns*32+si,13);ram_word<=saved(64*si+63 downto 64*si);
        if si=31 then saving<='0';si<=0;ns<=ns+1;else si<=si+1;end if;
      elsif qu>0 then
        item:=queue(qr);
        if item(256)='1' then
          if nc<256 then ram_write<='1';ram_address<=to_unsigned(6144+4*nc+qi,13);ram_word<=item(64*qi+63 downto 64*qi);end if;
          if qi=3 then
            qi<=0;rp:=advance(qr);count:=count-1;
            if nc<256 then nc<=nc+1;else lc:=lc+1;end if;
          else qi<=qi+1;end if;
        else
          if ne<1024 then ram_write<='1';ram_address<=to_unsigned(4096+2*ne+qi,13);ram_word<=item(64*qi+63 downto 64*qi);end if;
          if qi=1 then
            qi<=0;rp:=advance(qr);count:=count-1;
            if ne<1024 then ne<=ne+1;else le:=le+1;end if;
          else qi<=qi+1;end if;
        end if;
      elsif seal='1' and summary_valid_i='0' and holding_valid="0000" then
        w:=(others=>'0');
        case meta is
          when 0 => w:=x"5048595300030001";
          when 1 => w(31 downto 0):=std_logic_vector(page);w(47 downto 32):=std_logic_vector(to_unsigned(ns,16));w(49 downto 48):=std_logic_vector(board_i);
          when 2 => w(31 downto 0):=std_logic_vector(to_unsigned(ne,32));w(63 downto 32):=std_logic_vector(to_unsigned(nc,32));
          when 3 => w(31 downto 0):=std_logic_vector(le);w(63 downto 32):=std_logic_vector(lc);
          when 4 => w(31 downto 0):=config_i(31 downto 0);
          when 5 => w(31 downto 0):=config_i(63 downto 32);
          when 6 => w(31 downto 0):=config_i(95 downto 64);
          when 7 => w(31 downto 0):=config_i(127 downto 96);
          when 8 => w(31 downto 0):=config_i(159 downto 128);
          when 9 => w:=std_logic_vector(skipped_i);
          when 10 => w:=std_logic_vector(raw_i);
          when others => null;
        end case;
        if meta<16 then ram_write<='1';ram_address<=to_unsigned(7168+meta,13);ram_word<=w;end if;
        if meta=16 then frozen<='1';seal<='0';meta<=0;else meta<=meta+1;end if;
      end if;
      -- Serialize four independent event latches into ONE queue write port.
      -- This avoids inferring a multi-write register crossbar or replicated RAM.
      selected:=-1;
      if count<8 then
        for i in 0 to 3 loop
          port_index:=(round_robin+i) mod 4;
          if selected=-1 and hv(port_index)='1' then selected:=port_index;end if;
        end loop;
      end if;
      if selected>=0 then
        if selected>=2 then queue(wp)<='1' & holding(selected);else queue(wp)<='0' & holding(selected);end if;
        wp:=advance(wp);count:=count+1;hv(selected):='0';round_robin<=(selected+1) mod 4;
      end if;
      -- No new audit is admitted after sealing starts, so the page can freeze
      -- even while synchronization continues during a slow JTAG collection.
      if seal='0' and freeze_i='0' then
        if event_a_valid_i='1' then
          if hv(0)='0' then holding(0)<=x"00000000000000000000000000000000" & event_a_i;hv(0):='1';else le:=le+1;end if;
        end if;
        if event_b_valid_i='1' then
          if hv(1)='0' then holding(1)<=x"00000000000000000000000000000000" & event_b_i;hv(1):='1';else le:=le+1;end if;
        end if;
        if audit_a_i(255)='1' then
          if hv(2)='0' then holding(2)<=audit_a_i;hv(2):='1';else lc:=lc+1;end if;
          if audit_a_i(254)='1' then lc:=lc+1;end if;
        end if;
        if audit_b_i(255)='1' then
          if hv(3)='0' then holding(3)<=audit_b_i;hv(3):='1';else lc:=lc+1;end if;
          if audit_b_i(254)='1' then lc:=lc+1;end if;
        end if;
      end if;
      holding_valid<=hv;qr<=rp;qw<=wp;qu<=count;lost<=le;cal_lost<=lc;
    end if;
  end if;end process;
end;
