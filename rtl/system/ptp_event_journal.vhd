library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- A page contains at most 32 complete 256-bit audit records.  One complete
-- record can be written every clock without backpressuring PTP.  The host
-- reads one 64-bit word per clock; all unretained source events are counted.
entity ptp_event_journal is
  generic(G_MAX_EVENTS_PER_CYCLE:positive:=4);
  port(clk_i,rst_i:in std_logic;
    event_i:in std_logic_vector(255 downto 0);
    event_total_i:in natural range 0 to G_MAX_EVENTS_PER_CYCLE;
    freeze_i,ack_i:in std_logic;
    read_address_i:in unsigned(6 downto 0);
    read_data_o:out std_logic_vector(63 downto 0);
    frozen_o,capture_ready_o:out std_logic;
    count_o,capture_count_o:out natural range 0 to 32;
    lost_o,capture_lost_o:out unsigned(31 downto 0));
end;

architecture rtl of ptp_event_journal is
  type ram_t is array(0 to 31) of std_logic_vector(255 downto 0);
  signal ram:ram_t;
  attribute ram_style:string;
  attribute ram_style of ram:signal is "block";
  signal ram_read:std_logic_vector(255 downto 0);
  signal read_word:unsigned(1 downto 0):=(others=>'0');
  signal frozen,accept_event:std_logic:='0';
  signal count:natural range 0 to 32:=0;
  signal lost,next_lost:unsigned(31 downto 0):=(others=>'0');
begin
  -- Synchronous reset invalidates all rows through count; any reset-time write
  -- is discarded. Do not route the board's asynchronous reset into BRAM WE.
  accept_event<='1' when event_total_i>0 and frozen='0' and count<32
    and ack_i='0' else '0';
  next_lost<=lost+event_total_i-1 when accept_event='1' else lost+event_total_i;
  count_o<=count;lost_o<=lost;frozen_o<=frozen;
  capture_ready_o<=not (frozen or ack_i or rst_i);
  capture_count_o<=count+1 when accept_event='1' else count;
  capture_lost_o<=next_lost;

  read_data_o<=ram_read(64*to_integer(read_word)+63 downto 64*to_integer(read_word));
  -- One wide write port and one synchronous wide read infer four RAMB36s.
  -- This uses spare BRAM to preserve admission of one audit every clock, with
  -- no staging registers, serializer, or busy losses.  The word selector is
  -- registered alongside the RAM read to keep the 64-bit host latency at one
  -- clock.  There is no reset on RAM/data registers; count hides old contents.
  process(clk_i)
  begin
    if rising_edge(clk_i) then
      if accept_event='1' then ram(count)<=event_i;end if;
      ram_read<=ram(to_integer(read_address_i(6 downto 2)));
      read_word<=read_address_i(1 downto 0);
    end if;
  end process;

  process(clk_i)
  begin
    if rising_edge(clk_i) then
      if rst_i='1' then
        count<=0;lost<=(others=>'0');frozen<='0';
      else
        lost<=next_lost;
        if ack_i='1' then
          -- A coincident audit is discarded and counted; the following clock
          -- starts an empty page.  No pending write can survive an ACK.
          count<=0;frozen<='0';
        else
          if accept_event='1' then count<=count+1;end if;
          -- A coincident accepted record reaches RAM on this same edge and is
          -- included by capture_count/capture_lost in the atomic page header.
          if freeze_i='1' and frozen='0' then frozen<='1';end if;
        end if;
      end if;
    end if;
  end process;
end;
