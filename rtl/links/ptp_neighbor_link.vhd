-- Digital management stream, one independent FIFO per direction. RX has no
-- backpressure. Delay is from accepted TX word to presented RX word, in ticks.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity ptp_neighbor_link is
  generic(G_WORDS:positive:=64);
  port(clk_i,rst_i:in std_logic;delay_i:in natural range 1 to 4095;
    jitter_mask_i:in unsigned(7 downto 0);seed_i:in unsigned(31 downto 0);
    drop_every_i:in unsigned(15 downto 0);
    s_data_i:in std_logic_vector(15 downto 0);s_keep_i:in std_logic_vector(1 downto 0);
    s_valid_i,s_last_i:in std_logic;s_ready_o:out std_logic;
    m_data_o:out std_logic_vector(15 downto 0);m_keep_o:out std_logic_vector(1 downto 0);
    m_valid_o,m_last_o:out std_logic;idle_o:out std_logic;
    dropped_o:out unsigned(31 downto 0);
    source_raw_i:in std_logic_vector(63 downto 0):=(others=>'0');
    source_raw_o:out std_logic_vector(63 downto 0):=(others=>'0'));
end;
architecture rtl of ptp_neighbor_link is
  -- One synchronous packed RAM replaces three independently addressed LUT RAMs.
  -- Read the next head while consuming the current one, retaining the original
  -- output latency. A separate write-forward register covers empty enqueue and
  -- simultaneous last-pop/push without depending on a BRAM collision mode.
  type mem_t is array(0 to G_WORDS-1) of std_logic_vector(114 downto 0);
  signal mem:mem_t;
  attribute ram_style:string;
  attribute ram_style of mem:signal is "block";
  signal ram_head,forward_head,head,write_word:std_logic_vector(114 downto 0);
  signal forward_valid,enqueue,discard:std_logic:='0';
  signal peek:natural range 0 to G_WORDS-1:=0;
  signal word_jitter:natural range 0 to 255:=0;
  signal rd,wr:natural range 0 to G_WORDS-1:=0;
  signal count:natural range 0 to G_WORDS:=0;
  signal raw,lfsr,dropped:unsigned(31 downto 0):=(others=>'0');
  signal frame_count:unsigned(15 downto 0):=(others=>'0');
  signal in_frame,drop_frame,take_in,take_out:std_logic:='0';
  signal frame_jitter:natural range 0 to 255:=0;
  function advance(p:natural)return natural is
  begin if p=G_WORDS-1 then return 0;else return p+1;end if;end;
begin
  s_ready_o<='1' when count<G_WORDS else '0';take_in<=s_valid_i and s_ready_o;
  head<=forward_head when forward_valid='1' else ram_head;
  m_valid_o<='1' when count>0 and signed(raw-unsigned(head(50 downto 19)))>=0 else '0';take_out<=m_valid_o;
  m_data_o<=head(15 downto 0);m_keep_o<=head(17 downto 16);m_last_o<=head(18);
  idle_o<='1' when count=0 and in_frame='0' else '0';dropped_o<=dropped;
  source_raw_o<=head(114 downto 51);
  peek<=advance(rd) when take_out='1' else rd;
  process(all)
    variable drop_word:std_logic;
    variable jitter:natural range 0 to 255;
  begin
    drop_word:=drop_frame;jitter:=frame_jitter;
    if in_frame='0' then
      jitter:=to_integer(lfsr(7 downto 0) and jitter_mask_i);
      drop_word:='0';
      if drop_every_i/=0 and frame_count+1=drop_every_i then drop_word:='1';end if;
    end if;
    discard<=drop_word;word_jitter<=jitter;
  end process;
  -- Reset clears occupancy/pointers synchronously. Writes during reset are
  -- discarded; keeping reset out of WE avoids an asynchronous BRAM control.
  enqueue<=take_in and not discard;
  write_word<=source_raw_i&std_logic_vector(raw+delay_i+word_jitter)&s_last_i&s_keep_i&s_data_i;
  process(clk_i)
  begin if rising_edge(clk_i) then
    if enqueue='1' then mem(wr)<=write_word;end if;
    ram_head<=mem(peek);
    forward_valid<='0';
    if enqueue='1' and wr=peek then
      forward_valid<='1';forward_head<=write_word;
    end if;
  end if;end process;
  process(clk_i)
  begin if rising_edge(clk_i) then
    if rst_i='1' then
      rd<=0;wr<=0;count<=0;raw<=(others=>'0');lfsr<=seed_i;
      if seed_i=0 then lfsr<=to_unsigned(1,32);end if;
      dropped<=(others=>'0');frame_count<=(others=>'0');in_frame<='0';drop_frame<='0';frame_jitter<=0;
    else
      raw<=raw+1;
      if take_in='1' then
        if in_frame='0' then
          frame_jitter<=word_jitter;
          lfsr<=lfsr(30 downto 0)&(lfsr(31) xor lfsr(21) xor lfsr(1) xor lfsr(0));
          if discard='1' then frame_count<=(others=>'0');dropped<=dropped+1;drop_frame<='1';
          else frame_count<=frame_count+1;drop_frame<='0';end if;
        end if;
        in_frame<=not s_last_i;
        if enqueue='1' then wr<=advance(wr);end if;
      end if;
      if take_out='1' then rd<=advance(rd);end if;
      if enqueue='1' and take_out='0' then count<=count+1;
      elsif enqueue='0' and take_out='1' then count<=count-1;end if;
    end if;
  end if;end process;
end;
