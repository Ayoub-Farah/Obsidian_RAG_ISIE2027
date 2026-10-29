library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.sync_math_pkg.all;

-- Exact lower median, reusing one full-width signed comparison for 28 pairs.
-- A single history read mux serves operand loads, comparisons and selection:
-- seven operand loads + 28 comparisons + eight rank selections = 43 clocks.
-- values_i must remain stable until busy_o falls. Equal values are ranked in
-- increasing index order, exactly like sync_math_pkg.median.
entity sync_median_serial is
  port(clk_i,rst_i,sample_i:in std_logic;
       values_i:in hist_t;
       median_o:out signed(63 downto 0):=(others=>'0');
       busy_o:out std_logic:='0');
end;
architecture rtl of sync_median_serial is
  type ranks_t is array(0 to 7) of natural range 0 to 7;
  signal ranks:ranks_t:=(others=>0);
  signal first:natural range 0 to 6:=0;
  signal second:natural range 1 to 7:=1;
  signal selected,read_index:natural range 0 to 7:=0;
  signal phase:natural range 0 to 2:=0;
  signal operand_a,read_value:signed(63 downto 0):=(others=>'0');
  signal busy:std_logic:='0';
begin
  busy_o<=busy;
  read_index<=first when phase=0 else second when phase=1 else selected;
  read_value<=values_i(read_index);
  process(clk_i)
    variable updated:ranks_t;
  begin
    if rising_edge(clk_i) then
      if rst_i='1' then
        median_o<=(others=>'0');busy<='0';ranks<=(others=>0);first<=0;second<=1;selected<=0;phase<=0;
      elsif sample_i='1' then
        -- synthesis translate_off
        assert busy='0' report "PTP median input changed before the 43-clock calculation completed" severity failure;
        -- synthesis translate_on
        ranks<=(others=>0);first<=0;second<=1;selected<=0;phase<=0;busy<='1';
      elsif busy='1' then
        if phase=0 then operand_a<=read_value;phase<=1;
        elsif phase=1 then
          updated:=ranks;
          if operand_a<=read_value then updated(second):=updated(second)+1;
          else updated(first):=updated(first)+1;end if;
          ranks<=updated;
          if first=6 and second=7 then phase<=2;selected<=0;
          elsif second=7 then first<=first+1;second<=first+2;phase<=0;
          else second<=second+1;end if;
        else
          if ranks(selected)=3 then median_o<=read_value;end if;
          if selected=7 then busy<='0';else selected<=selected+1;end if;
        end if;
      end if;
    end if;
  end process;
end;
