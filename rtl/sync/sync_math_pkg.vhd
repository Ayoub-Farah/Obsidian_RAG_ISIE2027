library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
-- Exact lower median of eight signed Q48.16 values. Rank comparisons are
-- independent, avoiding the long data-dependent compare/swap chain.
package sync_math_pkg is
 type hist_t is array(0 to 7) of signed(63 downto 0);
 function median(v:hist_t) return signed;
end package;
package body sync_math_pkg is
 function median(v:hist_t) return signed is
  type rank_t is array(0 to 7) of natural range 0 to 7;
  variable ranks:rank_t:=(others=>0);
  variable result:signed(63 downto 0):=(others=>'0');
 begin
  for i in 0 to 6 loop
   for j in i+1 to 7 loop
    if v(i)<=v(j) then ranks(j):=ranks(j)+1;
    else ranks(i):=ranks(i)+1;end if;
   end loop;
  end loop;
  for i in 0 to 7 loop if ranks(i)=3 then result:=v(i);end if;end loop;
  return result;
 end function;
end package body;
