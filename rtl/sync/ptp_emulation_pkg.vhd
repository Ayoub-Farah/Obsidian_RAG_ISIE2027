library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

package ptp_emulation_pkg is
  type words16_t is array(natural range <>) of std_logic_vector(15 downto 0);
  type keeps_t is array(natural range <>) of std_logic_vector(1 downto 0);
  type words64_t is array(natural range <>) of std_logic_vector(63 downto 0);
  type words32_t is array(natural range <>) of std_logic_vector(31 downto 0);
  type audits_t is array(natural range <>) of std_logic_vector(255 downto 0);
  type steps_t is array(natural range <>) of unsigned(63 downto 0);
  type offsets_t is array(natural range <>) of signed(63 downto 0);
  type delays_t is array(natural range <>) of natural range 1 to 4095;
  function population(n:positive; board:natural) return natural;
  function first_node(n:positive; board:natural) return natural;
end;
package body ptp_emulation_pkg is
  function population(n:positive; board:natural) return natural is
    variable r:natural:=n/3;
  begin if board<n mod 3 then r:=r+1;end if;return r;end;
  function first_node(n:positive; board:natural) return natural is
    variable r:natural:=0;
  begin for b in 0 to 2 loop if b<board then r:=r+population(n,b);end if;end loop;return r;end;
end;
