-- A marker is generated from corrected local time, never from packet arrival.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity ptp_epoch_marker is
  port(clk_i,rst_i,enable_i:in std_logic;time_i:in std_logic_vector(63 downto 0);
    epoch_i:in unsigned(63 downto 0);period_i:in positive range 626 to 16777215;
    width_i:in positive range 1 to 625;
    pulse_o:out std_logic;index_o:out unsigned(63 downto 0);
    skipped_o,backsteps_o:out unsigned(31 downto 0));
end;
architecture rtl of ptp_epoch_marker is
  signal next_epoch,idx,previous:unsigned(63 downto 0):=(others=>'0');
  signal width:natural range 0 to 625:=0;
  signal skipped,backsteps:unsigned(31 downto 0):=(others=>'0');
  signal enabled,catching_up:std_logic:='0';
begin
  pulse_o<='1' when width>0 else '0';index_o<=idx;
  skipped_o<=skipped;backsteps_o<=backsteps;
  process(clk_i)
    variable period_q:unsigned(63 downto 0);
  begin if rising_edge(clk_i) then
    period_q:=shift_left(to_unsigned(period_i,64),16);
    if rst_i='1' then
      next_epoch<=epoch_i;idx<=(others=>'0');width<=0;enabled<='0';catching_up<='0';
      skipped<=(others=>'0');backsteps<=(others=>'0');previous<=unsigned(time_i);
    else
      previous<=unsigned(time_i);
      if width>0 then width<=width-1;end if;
      if enable_i='0' then enabled<='0';width<=0;next_epoch<=epoch_i;idx<=(others=>'0');
      elsif enabled='0' then enabled<='1';next_epoch<=epoch_i;idx<=(others=>'0');catching_up<='0';
      else
        if unsigned(time_i)<previous then backsteps<=backsteps+1;end if;
        if unsigned(time_i)>=next_epoch then
          -- Advance at most one index per tick. Do not emit catch-up pulses.
          if unsigned(time_i)-next_epoch>=period_q then
            skipped<=skipped+1;catching_up<='1';
          elsif catching_up='1' or width>0 then
            skipped<=skipped+1;catching_up<='0';
          else width<=width_i;end if;
          next_epoch<=next_epoch+period_q;idx<=idx+1;
        end if;
      end if;
    end if;
  end if;end process;
end;
