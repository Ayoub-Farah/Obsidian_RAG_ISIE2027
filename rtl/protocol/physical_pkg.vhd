-- Runtime, three-physical-board benchmark wire contract, version 2.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.benchmark_pkg.all;

package physical_pkg is
  constant C_CT : natural := 1;
  constant C_RAG : natural := 2;
  constant C_MAX_PAYLOAD : natural := 4096;
  constant C_MAX_SLOT : natural := 1365;
  constant C_HEADER_BYTES : natural := 32;
  subtype ticks_t is unsigned(63 downto 0);
  subtype config_t is std_logic_vector(159 downto 0);
  subtype control_payload_t is std_logic_vector(319 downto 0);
  subtype event_t is std_logic_vector(127 downto 0);
  subtype summary_t is std_logic_vector(2047 downto 0);
  constant C_DEFAULT_CONFIG : config_t := x"0000186A00000080000100021000000600000001";
  -- Config words, low word first: generation; P[31:16]/S[15:0];
  -- reserved[31:24]/mode[23:16]/H[15:0]; repetitions; period ticks.
  function make_config(generation, payload, slot, hops, mode : natural;
                         repetitions, period : unsigned(31 downto 0)) return config_t;
  function valid_config(c : config_t) return boolean;
  function cfg_payload(c : config_t) return natural;
  function cfg_slot(c : config_t) return natural;
  function cfg_hops(c : config_t) return natural;
  function cfg_mode(c : config_t) return natural;
  function header_byte(c : config_t; run_id, trial_id : std_logic_vector(31 downto 0);
                       origin, position : natural) return byte_t;
  function payload_byte(c : config_t; origin : natural;
                        trial_id : std_logic_vector(31 downto 0); position : natural) return byte_t;
  function make_event(stamp : ticks_t; trial_id : std_logic_vector(31 downto 0);
                      origin, hop, kind : natural; bad : std_logic := '0') return event_t;
end package;

package body physical_pkg is
  function make_config(generation, payload, slot, hops, mode : natural;
                         repetitions, period : unsigned(31 downto 0)) return config_t is
    variable c : config_t := (others=>'0');
  begin
    c(31 downto 0):=std_logic_vector(to_unsigned(generation,32));
    c(63 downto 32):=std_logic_vector(to_unsigned(payload,16)) & std_logic_vector(to_unsigned(slot,16));
    c(95 downto 64):=x"00" & std_logic_vector(to_unsigned(mode,8)) & std_logic_vector(to_unsigned(hops,16));
    c(127 downto 96):=std_logic_vector(repetitions); c(159 downto 128):=std_logic_vector(period);
    return c;
  end;
  function cfg_payload(c : config_t) return natural is begin return to_integer(unsigned(c(63 downto 48))); end;
  function cfg_slot(c : config_t) return natural is begin return to_integer(unsigned(c(47 downto 32))); end;
  function cfg_hops(c : config_t) return natural is begin return to_integer(unsigned(c(79 downto 64))); end;
  function cfg_mode(c : config_t) return natural is begin return to_integer(unsigned(c(87 downto 80))); end;
  function valid_config(c : config_t) return boolean is
    variable p,s,m : natural;
  begin
    p:=cfg_payload(c); s:=cfg_slot(c); m:=cfg_mode(c);
    return (m=C_CT or m=C_RAG) and p>=1 and p<=C_MAX_PAYLOAD and
      s>=1 and s<=C_MAX_SLOT and cfg_hops(c)>=1 and c(95 downto 88)=x"00" and
      unsigned(c(159 downto 128))/=0 and (m/=C_CT or p>=3*s);
  end;
  function header_byte(c : config_t; run_id, trial_id : std_logic_vector(31 downto 0);
                       origin, position : natural) return byte_t is
    variable v : std_logic_vector(31 downto 0);
  begin
    case position is
      when 0 => return x"C3"; when 1 => return x"5A"; when 2 => return x"02";
      when 3 => return c(87 downto 80);
      when 4 to 7 => v:=c(31 downto 0); return v(31-8*(position-4) downto 24-8*(position-4));
      when 8 to 11 => return run_id(31-8*(position-8) downto 24-8*(position-8));
      when 12 to 15 => return trial_id(31-8*(position-12) downto 24-8*(position-12));
      when 16 => return std_logic_vector(to_unsigned(origin,8));
      when 18 => return c(63 downto 56); when 19 => return c(55 downto 48);
      when 20 => return c(47 downto 40); when 21 => return c(39 downto 32);
      when 22 | 24 => return c(79 downto 72);
      when 23 | 25 => return c(71 downto 64);
      when others => return x"00";
    end case;
  end;
  function payload_byte(c : config_t; origin : natural;
                        trial_id : std_logic_vector(31 downto 0); position : natural) return byte_t is
    variable s : natural := cfg_slot(c);
  begin
    if cfg_mode(c)=C_RAG then return data_pattern(origin,trial_id,position);
    elsif position<s then return data_pattern(0,trial_id,position);
    elsif position<3*s then return x"00";
    else return data_pattern(3,trial_id,position); end if;
  end;
  function make_event(stamp : ticks_t; trial_id : std_logic_vector(31 downto 0);
                      origin, hop, kind : natural; bad : std_logic := '0') return event_t is
    variable e : event_t := (others=>'0');
  begin
    e(63 downto 0):=std_logic_vector(stamp); e(95 downto 64):=trial_id;
    e(111 downto 96):=std_logic_vector(to_unsigned(hop,16));
    e(113 downto 112):=std_logic_vector(to_unsigned(origin,2));
    e(117 downto 114):=std_logic_vector(to_unsigned(kind,4));e(118):=bad;
    return e;
  end;
end package body;
