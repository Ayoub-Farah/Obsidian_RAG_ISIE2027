library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- A frozen asynchronous implementation is the cycle-accurate reference. The
-- first phase independently checks one-tick enqueue latency; later phases add
-- full/wrapped FIFOs, partial frames, gaps, seeded jitter, loss and resets.
entity ptp_link_bram_checker is
  generic(G_WORDS:positive:=4;G_DELAY:positive:=37;G_ID:natural:=0);
  port(clk:in std_logic;done:out std_logic:='0');
end;
architecture test of ptp_link_bram_checker is
  signal rst:std_logic:='1';
  signal delay:natural range 1 to 4095:=1;
  signal jitter:unsigned(7 downto 0):=(others=>'0');
  signal seed:unsigned(31 downto 0):=to_unsigned(G_ID,32);
  signal drop_every:unsigned(15 downto 0):=(others=>'0');
  signal sd:std_logic_vector(15 downto 0):=(others=>'0');
  signal sk:std_logic_vector(1 downto 0):="11";
  signal sv,sl,accepted:std_logic:='0';
  signal tag:std_logic_vector(63 downto 0):=(others=>'0');
  signal ready_a,ready_b,valid_a,valid_b,last_a,last_b,idle_a,idle_b:std_logic;
  signal data_a,data_b:std_logic_vector(15 downto 0);
  signal keep_a,keep_b:std_logic_vector(1 downto 0);
  signal raw_a,raw_b:std_logic_vector(63 downto 0);
  signal drops_a,drops_b:unsigned(31 downto 0);
  signal cycle:natural:=0;
begin
  actual:entity work.ptp_neighbor_link generic map(G_WORDS)
    port map(clk,rst,delay,jitter,seed,drop_every,sd,sk,sv,sl,ready_a,
      data_a,keep_a,valid_a,last_a,idle_a,drops_a,tag,raw_a);
  reference:entity work.ptp_neighbor_link_async_reference generic map(G_WORDS)
    port map(clk,rst,delay,jitter,seed,drop_every,sd,sk,sv,sl,ready_b,
      data_b,keep_b,valid_b,last_b,idle_b,drops_b,tag,raw_b);
  process(clk) begin
    if rising_edge(clk) then accepted<=sv and ready_a and not rst;end if;
  end process;
  process
    variable rng:unsigned(31 downto 0):=to_unsigned(16#12345#+97*G_ID,32);
    variable remaining,serial:natural:=0;
    variable offer:boolean;
  begin
    for c in 1 to 70000 loop
      wait until falling_edge(clk);cycle<=c;
      rng:=rng xor shift_left(rng,13);rng:=rng xor shift_right(rng,17);rng:=rng xor shift_left(rng,5);
      if c<=4 or (c>=27000 and c<=27003) or (c>=45000 and c<=45003) then
        -- Deliberately offer poison throughout reset. Physical RAM writes are
        -- allowed while occupancy stays empty; none may escape after release.
        rst<='1';sv<='1';sl<='0';remaining:=0;
        sd<=x"DEAD";sk<="01";tag<=x"BAD0BAD0BAD0BAD0";
        delay<=4095;jitter<=to_unsigned(255,8);drop_every<=(others=>'0');
        if c>=27000 then seed<=to_unsigned(0,32);end if;
        if c>=45000 then seed<=to_unsigned(16#4321#+G_ID,32);end if;
      elsif c=5 or c=27004 or c=45004 then
        -- The very first non-reset edge must replace the complete poisoned
        -- head, with unchanged one-tick latency and raw-tag forwarding.
        rst<='0';sv<='1';sl<='1';remaining:=1;
        delay<=1;jitter<=(others=>'0');drop_every<=(others=>'0');
        sd<=std_logic_vector(to_unsigned(serial mod 65536,16));sk<="11";
        tag<=x"ABCD1234"&std_logic_vector(to_unsigned(serial+G_ID*1000000,32));
      else
        rst<='0';delay<=G_DELAY;
        case (c/119) mod 5 is
          when 0=>jitter<=to_unsigned(0,8);
          when 1=>jitter<=to_unsigned(1,8);
          when 2=>jitter<=to_unsigned(3,8);
          when 3=>jitter<=to_unsigned(7,8);
          when others=>jitter<=to_unsigned(255,8);
        end case;
        case (c/271) mod 4 is
          when 0=>drop_every<=to_unsigned(0,16);
          when 1=>drop_every<=to_unsigned(2,16);
          when 2=>drop_every<=to_unsigned(3,16);
          when others=>drop_every<=to_unsigned(7,16);
        end case;
        if c<80 then delay<=1;jitter<=(others=>'0');drop_every<=(others=>'0');end if;
        -- After the known first release frame, deterministically discard the
        -- next frame. Slow/full FIFOs need not hit a moving random threshold.
        if c>=27005 and c<27100 then drop_every<=to_unsigned(2,16);end if;
        if c>=62000 then jitter<=(others=>'0');drop_every<=(others=>'0');end if;
        if accepted='1' then remaining:=remaining-1;serial:=serial+1;end if;
        -- An offered word remains stable through FIFO backpressure.
        if sv='0' or accepted='1' then
          offer:=rng(2 downto 0)/=0;
          if c<600 then offer:=true;end if;
          if c>=27005 and c<27020 then offer:=true;end if;
          if c>=62000 then offer:=remaining>0;end if;
          if offer then
            if remaining=0 then
              remaining:=1+to_integer(rng(7 downto 4));
              if c<80 then remaining:=1;end if;
            end if;
            sv<='1';sl<='0';if remaining=1 then sl<='1';end if;
            sd<=std_logic_vector(to_unsigned(serial mod 65536,16));sk<=std_logic_vector(rng(9 downto 8));
            tag<=x"ABCD1234"&std_logic_vector(to_unsigned(serial+G_ID*1000000,32));
          else sv<='0';end if;
        end if;
      end if;
    end loop;
    wait until falling_edge(clk);
    assert idle_a='1' report "BRAM link failed to drain final complete frame" severity failure;
    done<='1';wait;
  end process;
  process
    variable output_count,input_count,full_count,loss_count,bypass_count:natural:=0;
    variable reset_offer_count,release_count:natural:=0;
    variable was_accepted,first_phase:boolean;
    variable captured_data:std_logic_vector(15 downto 0);
    variable captured_tag:std_logic_vector(63 downto 0);
  begin
    wait until rising_edge(clk);
    was_accepted:=sv='1' and ready_a='1' and rst='0';
    first_phase:=(cycle>=5 and cycle<80) or cycle=27004 or cycle=45004;
    captured_data:=sd;captured_tag:=tag;
    if rst='0' then
      if was_accepted then input_count:=input_count+1;end if;
      if ready_a='0' then full_count:=full_count+1;end if;
      if valid_a='1' then output_count:=output_count+1;end if;
      if first_phase and was_accepted and valid_a='1' then bypass_count:=bypass_count+1;end if;
      if drops_a/=0 then loss_count:=loss_count+1;end if;
      if cycle=5 or cycle=27004 or cycle=45004 then release_count:=release_count+1;end if;
    elsif sv='1' and ready_a='1' then
      reset_offer_count:=reset_offer_count+1;
    end if;
    wait for 1 ns;
    assert ready_a=ready_b and valid_a=valid_b and idle_a=idle_b and drops_a=drops_b
      report "BRAM link control mismatch checker="&integer'image(G_ID)&" cycle="&integer'image(cycle) severity failure;
    if rst='1' then
      assert ready_a='1' and valid_a='0' and idle_a='1' and drops_a=0
        report "Reset-time RAM write became a logical FIFO entry" severity failure;
    end if;
    if valid_a='1' then
      assert data_a=data_b and keep_a=keep_b and last_a=last_b and raw_a=raw_b
        report "BRAM link payload/stamp mismatch checker="&integer'image(G_ID)&" cycle="&integer'image(cycle) severity failure;
    end if;
    if first_phase then
      assert (valid_a='1')=was_accepted report "BRAM prefetch changed one-tick enqueue latency" severity failure;
      if was_accepted then
        assert data_a=captured_data and raw_a=captured_tag and last_a='1'
          report "BRAM empty/last-pop push write-forward incorrect" severity failure;
      end if;
    end if;
    if done='1' then
      assert input_count>4*G_WORDS and output_count>2*G_WORDS and full_count>0 and loss_count>0
        report "BRAM link missed wrap/full/loss checker="&integer'image(G_ID)&
          " input="&integer'image(input_count)&" output="&integer'image(output_count)&
          " full="&integer'image(full_count)&" loss="&integer'image(loss_count) severity failure;
      assert reset_offer_count>=9 and release_count=3
        report "BRAM link missed valid-during-reset or immediate fresh-push coverage" severity failure;
      if G_WORDS>1 then
        assert bypass_count>50 report "BRAM link missed simultaneous last-pop/push coverage" severity failure;
      end if;
    end if;
  end process;
end;

library ieee;
use ieee.std_logic_1164.all;
use std.env.all;
entity tb_ptp_link_bram_equivalence is end;
architecture test of tb_ptp_link_bram_equivalence is
  signal clk:std_logic:='0';signal done:std_logic_vector(0 to 5):=(others=>'0');
begin
  clk<=not clk after 8 ns;
  a:entity work.ptp_link_bram_checker generic map(1,1,0) port map(clk,done(0));
  b:entity work.ptp_link_bram_checker generic map(4,37,1) port map(clk,done(1));
  c:entity work.ptp_link_bram_checker generic map(8,4095,2) port map(clk,done(2));
  d:entity work.ptp_link_bram_checker generic map(128,1,3) port map(clk,done(3));
  e:entity work.ptp_link_bram_checker generic map(128,37,4) port map(clk,done(4));
  f:entity work.ptp_link_bram_checker generic map(128,4095,5) port map(clk,done(5));
  process begin
    wait until done="111111";wait for 32 ns;
    report "PASS BRAM link cycle equivalence: depths1/4/8/128, delays1/37/4095, jitter/loss/gaps, wrap/full, write-forward, valid-during-reset, immediate fresh pushes and64-bit raw tags" severity note;
    stop;
  end process;
end;
