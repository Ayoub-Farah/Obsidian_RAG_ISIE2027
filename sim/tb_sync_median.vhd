library ieee;use ieee.std_logic_1164.all;use ieee.numeric_std.all;use std.env.all;use work.sync_math_pkg.all;
entity tb_sync_median is end;
architecture test of tb_sync_median is
 function median_original(v:hist_t) return signed is
  variable a:hist_t:=v;variable t:signed(63 downto 0);
 begin
  for i in 1 to 7 loop for j in i downto 1 loop
   if a(j)<a(j-1) then t:=a(j);a(j):=a(j-1);a(j-1):=t;end if;
  end loop;end loop;
  return a(3);
 end function;
begin
 process
  variable rng:unsigned(63 downto 0):=x"8123456789ABCDEF";variable v:hist_t;
 begin
  for trial in 0 to 20000 loop
   for i in 0 to 7 loop
    rng:=rng(62 downto 0)&(rng(63) xor rng(62) xor rng(60) xor rng(59));
    case trial mod 5 is
     when 0 => v(i):=signed(rng);
     when 1 => v(i):=resize(signed(rng(2 downto 0)),64);
     when 2 => v(i):=to_signed(i,64);
     when 3 => v(i):=to_signed(7-i,64);
     when others => if i mod 2=0 then v(i):=signed'(x"8000000000000000");else v(i):=signed'(x"7FFFFFFFFFFFFFFF");end if;
    end case;
   end loop;
   assert median(v)=median_original(v) report "Median result changed" severity failure;
   wait for 1 ns;
  end loop;
  report "PASS median rank versus original sort, 20001 signed64 vectors including duplicates and extremes" severity note;
  stop;wait;
 end process;
end;
