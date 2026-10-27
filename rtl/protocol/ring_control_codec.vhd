-- Fixed 64-byte ring-control messages, with an independently checked CRC32.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.benchmark_pkg.all;
use work.physical_pkg.all;
entity ring_control_codec is
  port(clk_i,rst_i:in std_logic;raw_i:in ticks_t;board_i:in unsigned(1 downto 0);
    request_i:in std_logic;kind_i:in byte_t;sequence_i:in std_logic_vector(31 downto 0);
    timestamp_i:in std_logic_vector(63 downto 0);payload_i:in control_payload_t;
    ready_o:out std_logic;
    tx_data_o:out std_logic_vector(15 downto 0);tx_keep_o:out std_logic_vector(1 downto 0);
    tx_valid_o,tx_last_o:out std_logic;tx_ready_i:in std_logic;
    rx_data_i:in std_logic_vector(15 downto 0);rx_keep_i:in std_logic_vector(1 downto 0);
    rx_valid_i,rx_last_i:in std_logic;rx_stamp_i:in ticks_t;
    event_o,error_o:out std_logic;kind_o:out byte_t;source_o:out unsigned(1 downto 0);
    sequence_o:out std_logic_vector(31 downto 0);timestamp_o:out std_logic_vector(63 downto 0);
    payload_o:out control_payload_t;stamp_o:out ticks_t);
end;
architecture rtl of ring_control_codec is
  signal busy:std_logic:='0';signal ti:natural range 0 to 31:=0;
  signal message:std_logic_vector(479 downto 0):=(others=>'0');
  signal tc,rc:std_logic_vector(31 downto 0):=x"FFFFFFFF";
  signal ri:natural range 0 to 32:=0;
  signal rm:std_logic_vector(479 downto 0):=(others=>'0');
  signal first:ticks_t:=(others=>'0');signal malformed:std_logic:='0';
  signal tw:std_logic_vector(15 downto 0);
begin
  ready_o<=not busy;tx_valid_o<=busy;tx_keep_o<="11";tx_last_o<='1' when busy='1' and ti=31 else '0';
  tx_data_o<=tw;
  process(all)
    variable c:std_logic_vector(31 downto 0);
  begin
    c:=not tc;
    if ti<30 then tw<=message(479-16*ti downto 464-16*ti);
    elsif ti=30 then tw<=c(7 downto 0)&c(15 downto 8);
    else tw<=c(23 downto 16)&c(31 downto 24);end if;
  end process;
  process(clk_i)
    variable m:std_logic_vector(479 downto 0);variable c:std_logic_vector(31 downto 0);
    variable bad:std_logic;
  begin if rising_edge(clk_i) then
    event_o<='0';error_o<='0';
    if rst_i='1' then busy<='0';ti<=0;ri<=0;malformed<='0';tc<=x"FFFFFFFF";rc<=x"FFFFFFFF";
    else
      if busy='0' and request_i='1' then
        message<=x"D3A701" & kind_i & "000000" & std_logic_vector(board_i) & x"000000" & sequence_i & timestamp_i & payload_i;
        busy<='1';ti<=0;tc<=x"FFFFFFFF";
      elsif busy='1' and tx_ready_i='1' then
        if ti<30 then tc<=crc32_byte(crc32_byte(tc,tw(15 downto 8)),tw(7 downto 0));end if;
        if ti=31 then busy<='0';ti<=0;else ti<=ti+1;end if;
      end if;
      if rx_valid_i='1' then
        m:=rm;bad:=malformed;c:=rc;
        if ri=0 then c:=x"FFFFFFFF";bad:='0';first<=rx_stamp_i;end if;
        c:=crc32_byte(crc32_byte(c,rx_data_i(15 downto 8)),rx_data_i(7 downto 0));
        if ri<30 then m(479-16*ri downto 464-16*ri):=rx_data_i;end if;
        if rx_keep_i/="11" or ri>=32 then bad:='1';end if;
        if rx_last_i='1' then
          if ri/=31 or m(479 downto 456)/=x"D3A701" or m(447 downto 442)/="000000" or
            m(441 downto 440)="11" or c/=x"DEBB20E3" then bad:='1';end if;
          if bad='0' then
            event_o<='1';kind_o<=m(455 downto 448);source_o<=unsigned(m(441 downto 440));
            sequence_o<=m(415 downto 384);timestamp_o<=m(383 downto 320);payload_o<=m(319 downto 0);stamp_o<=first;
          else error_o<='1';end if;
          ri<=0;malformed<='0';
        else
          if ri<32 then ri<=ri+1;end if;rm<=m;malformed<=bad;
        end if;
        rc<=c;
      end if;
    end if;
  end if;end process;
end;
