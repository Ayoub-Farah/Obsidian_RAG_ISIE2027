library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

package benchmark_pkg is
  subtype byte_t is std_logic_vector(7 downto 0);
  type byte_array_t is array(natural range <>) of byte_t;
  type word_array_t is array(natural range <>) of std_logic_vector(15 downto 0);
  type keep_array_t is array(natural range <>) of std_logic_vector(1 downto 0);
  type u32_array_t is array(natural range <>) of std_logic_vector(31 downto 0);
  function crc16_byte(crc: std_logic_vector(15 downto 0); b: byte_t) return std_logic_vector;
  -- Running reflected CRC; initialise FFFFFFFF, complement before transmission.
  function crc32_byte(crc: std_logic_vector(31 downto 0); b: byte_t) return std_logic_vector;
  function data_pattern(node: natural; cycle: std_logic_vector(31 downto 0); j:natural) return byte_t;
  function ref_pattern(node: natural; cycle: std_logic_vector(31 downto 0); j:natural) return byte_t;
  function make_header(kind,origin,nodes,payload:natural; cycle:std_logic_vector(31 downto 0)) return byte_array_t;
end package;

package body benchmark_pkg is
  function crc16_byte(crc:std_logic_vector(15 downto 0);b:byte_t) return std_logic_vector is
    variable c:unsigned(15 downto 0):=unsigned(crc) xor shift_left(resize(unsigned(b),16),8);
  begin
    for k in 0 to 7 loop
      if c(15)='1' then c:=shift_left(c,1) xor x"1021"; else c:=shift_left(c,1); end if;
    end loop; return std_logic_vector(c);
  end;
  function crc32_byte(crc:std_logic_vector(31 downto 0);b:byte_t) return std_logic_vector is
    variable c:unsigned(31 downto 0):=unsigned(crc) xor resize(unsigned(b),32);
  begin
    for k in 0 to 7 loop
      if c(0)='1' then c:=shift_right(c,1) xor x"EDB88320"; else c:=shift_right(c,1); end if;
    end loop; return std_logic_vector(c);
  end;
  function data_pattern(node:natural;cycle:std_logic_vector(31 downto 0);j:natural) return byte_t is
  begin return std_logic_vector(to_unsigned((90+17*(node mod 256)+31*to_integer(unsigned(cycle(7 downto 0)))+j) mod 256,8));end;
  function ref_pattern(node:natural;cycle:std_logic_vector(31 downto 0);j:natural) return byte_t is
  begin return std_logic_vector(to_unsigned((165+29*(node mod 256)+13*to_integer(unsigned(cycle(7 downto 0)))+j) mod 256,8));end;
  function make_header(kind,origin,nodes,payload:natural;cycle:std_logic_vector(31 downto 0)) return byte_array_t is
    variable h:byte_array_t(0 to 15);variable c:std_logic_vector(15 downto 0):=x"FFFF";
  begin
    h(0):=x"C3";h(1):=x"5A";h(2):=x"01";h(3):=std_logic_vector(to_unsigned(kind,8));
    h(4):=std_logic_vector(to_unsigned(origin/256,8));h(5):=std_logic_vector(to_unsigned(origin mod 256,8));
    h(6):=std_logic_vector(to_unsigned(nodes/256,8));h(7):=std_logic_vector(to_unsigned(nodes mod 256,8));
    for i in 0 to 3 loop h(8+i):=cycle(31-8*i downto 24-8*i);end loop;
    h(12):=std_logic_vector(to_unsigned(payload/256,8));h(13):=std_logic_vector(to_unsigned(payload mod 256,8));
    for i in 0 to 13 loop c:=crc16_byte(c,h(i));end loop;
    h(14):=c(15 downto 8);h(15):=c(7 downto 0);return h;
  end;
end package body;
