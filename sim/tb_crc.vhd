library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;
use work.benchmark_pkg.all;

entity tb_crc is end entity;
architecture test of tb_crc is
begin
  process
    constant ascii_digits : byte_array_t(0 to 8) :=
      (x"31", x"32", x"33", x"34", x"35", x"36", x"37", x"38", x"39");
    constant expected_header : std_logic_vector(127 downto 0) :=
      x"C35A0101000100030102030400065B94";
    variable c16 : std_logic_vector(15 downto 0);
    variable c32 : std_logic_vector(31 downto 0);
    variable header : byte_array_t(0 to 15);
    variable cycle : std_logic_vector(31 downto 0);
  begin
    c16 := x"FFFF";
    c32 := x"FFFFFFFF";
    for j in ascii_digits'range loop
      c16 := crc16_byte(c16, ascii_digits(j));
      c32 := crc32_byte(c32, ascii_digits(j));
    end loop;
    assert c16 = x"29B1" report "CRC16 golden mismatch" severity failure;
    assert not c32 = x"CBF43926" report "CRC32 golden mismatch" severity failure;

    cycle := x"01020304";
    header := make_header(1, 1, 3, 6, cycle);
    c32 := x"FFFFFFFF";
    for j in header'range loop
      assert header(j) = expected_header(127 - 8*j downto 120 - 8*j)
        report "Header wire vector mismatch at byte " & integer'image(j) severity failure;
      c32 := crc32_byte(c32, header(j));
    end loop;
    for j in 0 to 5 loop
      assert data_pattern(1, cycle, j) = std_logic_vector(to_unsigned(16#E7# + j, 8))
        report "Data pattern mismatch" severity failure;
      c32 := crc32_byte(c32, data_pattern(1, cycle, j));
    end loop;
    assert not c32 = x"1C8B7A74" report "Full DATA frame CRC mismatch" severity failure;

    -- The formula depends on all bits of cycle modulo 256; test overflow-safe
    -- implementation against independent reduced arithmetic for high values.
    cycle := x"FFFFFFFF";
    for node in 0 to 10 loop
      for j in 0 to 127 loop
        assert data_pattern(65524 + node, cycle, j) = std_logic_vector(to_unsigned(
          (90 + 17*((65524 + node) mod 256) + 31*255 + j) mod 256, 8))
          report "High-ID/high-cycle data pattern mismatch" severity failure;
        assert ref_pattern(65524 + node, cycle, j) = std_logic_vector(to_unsigned(
          (165 + 29*((65524 + node) mod 256) + 13*255 + j) mod 256, 8))
          report "High-ID/high-cycle reference pattern mismatch" severity failure;
      end loop;
    end loop;
    report "PASS tb_crc: CRC golden, exact header/frame vector and patterns" severity note;
    stop;
    wait;
  end process;
end architecture;
