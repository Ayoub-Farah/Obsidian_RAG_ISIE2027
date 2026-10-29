-- Local, independent observation COMMIT. Every pin has one output register.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity ptp_observer is
  generic(G_CAPACITY:positive:=20);
  port(clk_i,rst_i:in std_logic;first_i:in natural;count_i:in natural;
    pulses_i:in std_logic_vector(0 to G_CAPACITY-1);
    shadow_i:in unsigned(15 downto 0);apply_i,enable_i:in std_logic;
    ref_owner_i:in std_logic;ref_o,obs_o:out std_logic;
    active_o:out unsigned(15 downto 0);valid_o,error_o:out std_logic);
end;
architecture rtl of ptp_observer is
  signal selected,target:natural range 0 to G_CAPACITY-1:=0;
  signal active_id:unsigned(15 downto 0):=(others=>'0');
  signal valid,error,pending,waiting,enabled,prev_apply,pin:std_logic:='0';
  signal target_enabled:std_logic:='0';
begin
  active_o<=active_id;valid_o<=valid;error_o<=error;obs_o<=pin;
  process(clk_i)
    variable requested:natural;
  begin if rising_edge(clk_i) then
    prev_apply<=apply_i;
    if rst_i='1' then
      selected<=0;target<=0;active_id<=to_unsigned(first_i,16);valid<='0';error<='0';
      pending<='0';waiting<='0';enabled<='0';prev_apply<='0';pin<='0';ref_o<='0';
    else
      ref_o<=pulses_i(0) and ref_owner_i;
      pin<='0';
      if enabled='1' then pin<=pulses_i(selected);end if;
      if to_integer(active_id)<first_i or to_integer(active_id)>=first_i+count_i then
        valid<='0';enabled<='0';pending<='0';waiting<='0';
      end if;
      if apply_i='1' and prev_apply='0' then
        requested:=to_integer(shadow_i);
        if pending='1' or waiting='1' or requested<first_i or requested>=first_i+count_i then error<='1';
        else target<=requested-first_i;target_enabled<=enable_i;pending<='1';valid<='0';error<='0';end if;
      end if;
      -- Finish the old high interval before touching the mux. Wait for a low
      -- level on the target, so joining a pulse cannot create a spurious edge.
      if pending='1' and pin='0' and (enabled='0' or pulses_i(selected)='0') then
        enabled<='0';selected<=target;active_id<=to_unsigned(first_i+target,16);
        pending<='0';waiting<='1';pin<='0';
      elsif waiting='1' and pulses_i(selected)='0' then
        waiting<='0';enabled<=target_enabled;valid<=target_enabled;
      end if;
    end if;
  end if;end process;
end;
