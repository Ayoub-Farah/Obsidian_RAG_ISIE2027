library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- Non-backpressured ingress demultiplexer. The first two accepted physical
-- words classify the entire frame; VALID gaps do not restart classification.
-- Data and malformed magic reach the data parser. Management frames are
-- consumed here while the independent management codec sees the original RX.
-- An overflow is sticky and requires reset; it can leave a truncated frame.
entity data_frame_filter is
  generic(G_FIFO_WORDS:positive:=256);
  port(clk_i,rst_i:in std_logic;
    rx_data_i:in std_logic_vector(15 downto 0);rx_keep_i:in std_logic_vector(1 downto 0);
    rx_valid_i,rx_last_i:in std_logic;
    tx_data_o:out std_logic_vector(15 downto 0);tx_keep_o:out std_logic_vector(1 downto 0);
    tx_valid_o,tx_last_o:out std_logic;tx_ready_i:in std_logic;
    empty_o,overflow_o:out std_logic;highwater_o:out std_logic_vector(15 downto 0));
end;
architecture rtl of data_frame_filter is
  type memory_t is array(0 to G_FIFO_WORDS-1) of std_logic_vector(18 downto 0);
  signal memory:memory_t;
  signal rd,wr,desc_rd,desc_wr,current_desc:natural range 0 to G_FIFO_WORDS-1:=0;
  signal count,desc_count,hw:natural range 0 to G_FIFO_WORDS:=0;
  type decision_memory_t is array(0 to G_FIFO_WORDS-1) of std_logic_vector(0 downto 0);
  signal decisions:decision_memory_t;
  signal head_forward,decision_we,decision_value:std_logic;
  signal decision_addr:natural range 0 to G_FIFO_WORDS-1;
  signal orphan_pending:std_logic:='0';
  signal orphan_desc:natural range 0 to G_FIFO_WORDS-1:=0;
  signal input_active,input_discard,magic_ok:std_logic:='0';
  signal first_pending:std_logic:='0';signal overflow:std_logic:='0';
  signal available,consume,accept_word,retire_frame:std_logic;
  function inc(v:natural) return natural is
  begin if v=G_FIFO_WORDS-1 then return 0;else return v+1;end if;end;
begin
  assert G_FIFO_WORDS>=2 and G_FIFO_WORDS<65536 report "Filter FIFO size must be 2..65535 words" severity failure;
  head_forward<=decisions(desc_rd)(0);
  -- Arrival order guarantees that only the current first word can await
  -- classification. Retired decisions need no clearing; every new descriptor
  -- is hidden until its first/second word writes the decision memory.
  -- Retain an unclassified orphan after overflow until explicit reset.
  available<='1' when count>0 and desc_count>0
    and not (first_pending='1' and desc_rd=current_desc)
    and not (orphan_pending='1' and desc_rd=orphan_desc) else '0';
  tx_valid_o<=available and head_forward;
  consume<=available and (not head_forward or tx_ready_i);
  retire_frame <= consume and memory(rd)(18);
  accept_word <= '1' when rx_valid_i='1' and input_discard='0'
    and (count<G_FIFO_WORDS or consume='1')
    and (input_active='1' or desc_count<G_FIFO_WORDS or retire_frame='1') else '0';
  decision_we <= accept_word and ((not input_active and rx_last_i) or (input_active and first_pending));
  decision_addr <= desc_wr when input_active='0' else current_desc;
  decision_value <= '1' when input_active='0' or magic_ok='0' or unsigned(rx_data_i(7 downto 0))<16 else '0';
  process(clk_i) begin
    if rising_edge(clk_i) then
      if rst_i='0' and decision_we='1' then decisions(decision_addr)(0)<=decision_value;end if;
    end if;
  end process;
  tx_data_o<=memory(rd)(15 downto 0);tx_keep_o<=memory(rd)(17 downto 16);tx_last_o<=memory(rd)(18);
  empty_o<='1' when count=0 and desc_count=0 else '0';
  overflow_o<=overflow;highwater_o<=std_logic_vector(to_unsigned(hw,16));
  process(clk_i)
    variable c,d:natural;
  begin
    if rising_edge(clk_i) then
      if rst_i='1' then
        rd<=0;wr<=0;desc_rd<=0;desc_wr<=0;current_desc<=0;count<=0;desc_count<=0;hw<=0;
        input_active<='0';input_discard<='0';magic_ok<='0';first_pending<='0';overflow<='0';orphan_pending<='0';orphan_desc<=0;
      else
        c:=count;d:=desc_count;
        if consume='1' then
          c:=c-1;rd<=inc(rd);
          if memory(rd)(18)='1' then
            desc_rd<=inc(desc_rd);d:=d-1;
          end if;
        end if;
        if rx_valid_i='1' then
          if input_discard='1' then
            if rx_last_i='1' then input_discard<='0';input_active<='0';end if;
          elsif c<G_FIFO_WORDS and (input_active='1' or d<G_FIFO_WORDS) then
            memory(wr)<=rx_last_i&rx_keep_i&rx_data_i;wr<=inc(wr);c:=c+1;
            if input_active='0' then
              current_desc<=desc_wr;desc_wr<=inc(desc_wr);d:=d+1;
              input_active<='1';first_pending<='1';
              if rx_data_i=x"C35A" and rx_keep_i="11" then magic_ok<='1';else magic_ok<='0';end if;
            elsif first_pending='1' then
              first_pending<='0';


            end if;
            if rx_last_i='1' then
              input_active<='0';first_pending<='0';
              -- Short malformed frames must reach the data parser as errors.


            end if;
          else
            if first_pending='1' and orphan_pending='0' then orphan_pending<='1';orphan_desc<=current_desc;end if;
            overflow<='1';if rx_last_i='0' then input_discard<='1';else input_discard<='0';input_active<='0';end if;
          end if;
        end if;
        count<=c;desc_count<=d;if c>hw then hw<=c;end if;
      end if;
    end if;
  end process;
end;
