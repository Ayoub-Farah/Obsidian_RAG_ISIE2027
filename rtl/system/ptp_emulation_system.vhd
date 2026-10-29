library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.ptp_emulation_pkg.all;
entity ptp_emulation_system is
  generic(G_CAPACITY:positive:=1;G_MAX_NODES:positive:=3;G_ARM_DELAY:positive:=312500);
  port(clk_i,rst_i,links_up_i:in std_logic;
    address_i:in unsigned(15 downto 0);write_data_i:in std_logic_vector(63 downto 0);
    write_i,commit_i,start_i,stop_i:in std_logic;role_i:in unsigned(1 downto 0);
    obs_node_shadow_i:in unsigned(15 downto 0);obs_apply_i,obs_enable_i:in std_logic;
    snapshot_i,page_ack_i:in std_logic;
    read_data_o:out std_logic_vector(63 downto 0);status_o:out std_logic_vector(255 downto 0);
    obs_status_o,config_id_o:out std_logic_vector(63 downto 0);
    test_ref_m1_o,test_obs_o:out std_logic;
    left_rx_data_i,right_rx_data_i:in std_logic_vector(15 downto 0);
    left_rx_keep_i,right_rx_keep_i:in std_logic_vector(1 downto 0);
    left_rx_valid_i,left_rx_last_i,right_rx_valid_i,right_rx_last_i:in std_logic;
    left_tx_data_o,right_tx_data_o:out std_logic_vector(15 downto 0);
    left_tx_keep_o,right_tx_keep_o:out std_logic_vector(1 downto 0);
    left_tx_valid_o,left_tx_last_o,right_tx_valid_o,right_tx_last_o:out std_logic;
    left_tx_ready_i,right_tx_ready_i:in std_logic);
end;
architecture rtl of ptp_emulation_system is
  constant C_WORDS:positive:=16+4*G_CAPACITY;
  constant C_PAGE_WORDS:positive:=8+16*G_CAPACITY;
  type bank_t is array(0 to C_WORDS-1) of std_logic_vector(63 downto 0);
  type page_t is array(0 to C_PAGE_WORDS-1) of std_logic_vector(63 downto 0);
  function csr_mask(word:natural) return std_logic_vector is
  begin
    case word is
      when 0 => return x"000000000000FFFF"; -- node count
      when 1 => return x"0000FFFF00FFFFFF"; -- maintenance ratio, period
      when 2 => return x"FFFFFFFFFFFFFFFF"; -- complete Q48.16 epoch
      when 3 => return x"0000FFFF00FF03FF"; -- drop interval, jitter, pulse width
      when 4 to 7 => return x"FFFFFFFFFFFFFFFF"; -- IDs, sample/seed, duration
      when 8 to 15 => return x"0000000000000000";
      when others =>
        case (word-16) mod 4 is
          when 0 => return x"00000001FFFFFFFF"; -- full supported Q32.32 step
          when 1 => return x"FFFFFFFFFFFFFFFF"; -- signed Q48.16 offset
          when 2 => return x"000000000FFF0FFF"; -- two 12-bit link delays
          when others => return x"0000000000000000";
        end case;
    end case;
  end;
  function defaults return bank_t is
    variable b:bank_t:=(others=>(others=>'0'));
  begin
    b(0):=x"0000000000000003";b(1):=x"0000000A0000186A";
    b(2):=x"00000007A1200000";b(3):=x"0000000000000040";
    b(6):=x"0000F42400000001";
    for i in 0 to G_CAPACITY-1 loop b(16+4*i):=x"0000000100000000";b(18+4*i):=x"0000000000010001";end loop;
    return b;
  end;
  signal shadow,active:bank_t:=defaults;
  signal page:page_t:=(others=>(others=>'0'));
  signal configured,config_error,state_reset,start,stop,idle,overflow,frozen:std_logic:='0';
  signal previous_write,previous_commit,previous_start,previous_snapshot,previous_ack:std_logic:='0';
  signal board:natural range 0 to 2:=0;signal nodes:positive range 3 to G_MAX_NODES:=3;
  signal first:natural:=0;signal count:positive:=1;
  signal period:positive range 626 to 16777215:=6250;signal interval:positive range 1 to 65535:=10;
  signal width:positive range 1 to 625:=64;
  signal steps:steps_t(0 to G_CAPACITY-1);signal offsets:offsets_t(0 to G_CAPACITY-1);
  signal fwd,rev:delays_t(0 to G_CAPACITY-1);
  signal raw:std_logic_vector(63 downto 0);
  signal times,corrections,delays,theta,ages,indices:words64_t(0 to G_CAPACITY-1);
  signal accepted,rejected,deferred,skipped,backsteps:words32_t(0 to G_CAPACITY-1);
  signal dropped:words32_t(0 to G_CAPACITY-1);
  signal running,locked,holdover,errors,pulses:std_logic_vector(0 to G_CAPACITY-1);
  signal al,ar:audits_t(0 to G_CAPACITY-1);
  signal obs_active:unsigned(15 downto 0);signal obs_valid,obs_error,ref_owner:std_logic;
  signal page_id,missed,event_lost:unsigned(31 downto 0):=(others=>'0');
  signal sample_age:unsigned(31 downto 0):=(others=>'0');
  signal event_count:natural range 0 to 32:=0;
  signal journal_data:std_logic_vector(63 downto 0);
  signal journal_event:std_logic_vector(255 downto 0);
  signal journal_total:natural range 0 to 4*G_CAPACITY:=0;
  signal freeze_request,ack_request,capture_ready:std_logic;
  signal capture_count:natural range 0 to 32:=0;
  signal capture_lost:unsigned(31 downto 0);
  signal elapsed:unsigned(63 downto 0):=(others=>'0');signal measuring,nominal_seen,previous_local_locked,all_running:std_logic:='0';
  signal halt:std_logic:='0';
begin
  stop<=stop_i or halt;
  first<=first_node(nodes,board);count<=population(nodes,board);
  config_id_o<=active(4);ref_owner<='1' when board=0 and configured='1' else '0';
  obs_status_o<=(63 downto 18=>'0')&obs_error&obs_valid&std_logic_vector(obs_active);
  period<=to_integer(unsigned(active(1)(23 downto 0)));interval<=to_integer(unsigned(active(1)(47 downto 32)));
  width<=to_integer(unsigned(active(3)(9 downto 0)));
  params:for i in 0 to G_CAPACITY-1 generate
    steps(i)<=unsigned(active(16+4*i));offsets(i)<=signed(active(17+4*i));
    fwd(i)<=to_integer(unsigned(active(18+4*i)(11 downto 0)));
    rev(i)<=to_integer(unsigned(active(18+4*i)(27 downto 16)));
  end generate;
  core:entity work.ptp_emulation_core generic map(G_CAPACITY,G_MAX_NODES,G_ARM_DELAY)
    port map(clk_i,rst_i,state_reset or not configured,start,stop,links_up_i,nodes,board,
      steps,offsets,fwd,rev,unsigned(active(3)(23 downto 16)),unsigned(active(6)(31 downto 0)),unsigned(active(3)(47 downto 32)),
      period,interval,unsigned(active(2)),width,
      left_rx_data_i,right_rx_data_i,left_rx_keep_i,right_rx_keep_i,left_rx_valid_i,left_rx_last_i,right_rx_valid_i,right_rx_last_i,
      left_tx_data_o,right_tx_data_o,left_tx_keep_o,right_tx_keep_o,left_tx_valid_o,left_tx_last_o,right_tx_valid_o,right_tx_last_o,
      left_tx_ready_i,right_tx_ready_i,raw,times,corrections,delays,theta,ages,accepted,rejected,deferred,skipped,backsteps,indices,
      running,locked,holdover,errors,pulses,al,ar,idle,overflow,dropped);
  observer:entity work.ptp_observer generic map(G_CAPACITY)
    port map(clk_i,rst_i or state_reset,first,count,pulses,obs_node_shadow_i,obs_apply_i,obs_enable_i,ref_owner,
      test_ref_m1_o,test_obs_o,obs_active,obs_valid,obs_error);
  freeze_request<='1' when (snapshot_i='1' and previous_snapshot='0') or
    (measuring='1' and sample_age+1>=unsigned(active(6)(63 downto 32))) else '0';
  ack_request<=page_ack_i and not previous_ack;
  process(all)
    variable ev:std_logic_vector(255 downto 0);variable total:natural range 0 to 4*G_CAPACITY;
  begin
    total:=0;ev:=(others=>'0');
    for i in 0 to G_CAPACITY-1 loop
      if i<count then
        if al(i)(255)='1' then ev:=al(i);total:=total+1;if al(i)(254)='1' then total:=total+1;end if;end if;
        if ar(i)(255)='1' then ev:=ar(i);total:=total+1;if ar(i)(254)='1' then total:=total+1;end if;end if;
      end if;
    end loop;
    journal_event<=ev;journal_total<=total;
  end process;
  journal:entity work.ptp_event_journal generic map(4*G_CAPACITY)
    port map(clk_i,rst_i or state_reset,journal_event,journal_total,freeze_request,ack_request,
      address_i(6 downto 0),journal_data,frozen,capture_ready,event_count,capture_count,event_lost,capture_lost);
  process(all)
    variable s:std_logic_vector(255 downto 0);variable all_run,all_locked,any_error,any_hold:std_logic;variable a:natural;
  begin
    s:=(others=>'0');all_run:='1';all_locked:='1';any_error:=overflow;any_hold:='0';
    for i in 0 to G_CAPACITY-1 loop if i<count then
      all_run:=all_run and running(i);all_locked:=all_locked and locked(i);any_error:=any_error or errors(i);any_hold:=any_hold or holdover(i);
    end if;end loop;
    s(255 downto 232):=x"505401";s(0):=configured;s(1):=config_error;s(2):=idle;s(3):=all_run;
    all_running<=all_run;
    s(4):=all_locked;s(5):=any_hold;s(6):=any_error;s(7):=frozen;s(9 downto 8):=std_logic_vector(to_unsigned(board,2));
    s(10):=nominal_seen;s(11):=measuring;s(12):=halt;
    s(31 downto 16):=std_logic_vector(to_unsigned(G_CAPACITY,16));s(47 downto 32):=std_logic_vector(to_unsigned(nodes,16));
    s(63 downto 48):=std_logic_vector(to_unsigned(first,16));s(95 downto 64):=std_logic_vector(page_id);
    s(127 downto 96):=std_logic_vector(missed);s(159 downto 128):=std_logic_vector(event_lost);
    s(175 downto 160):=std_logic_vector(to_unsigned(event_count,16));s(231 downto 176):=raw(55 downto 0);status_o<=s;
    a:=to_integer(address_i);read_data_o<=(others=>'0');
    if a<C_WORDS then read_data_o<=shadow(a);
    elsif a>=16384 and a<16384+C_WORDS then read_data_o<=active(a-16384);
    elsif a>=32768 and a<32768+C_PAGE_WORDS then read_data_o<=page(a-32768);
    elsif a>=36864 and a<36992 then read_data_o<=journal_data;end if;
  end process;
  process(clk_i)
    variable valid_cfg,do_sample:boolean;variable n,p,w,dt:natural;
  begin if rising_edge(clk_i) then
    previous_write<=write_i;previous_commit<=commit_i;previous_start<=start_i;previous_snapshot<=snapshot_i;previous_ack<=page_ack_i;
    state_reset<='0';start<='0';do_sample:=freeze_request='1';previous_local_locked<=locked(0);
    if rst_i='1' then
      shadow<=defaults;active<=defaults;nodes<=3;board<=0;configured<='0';config_error<='0';state_reset<='1';
      page_id<=(others=>'0');missed<=(others=>'0');
      sample_age<=(others=>'0');elapsed<=(others=>'0');measuring<='0';nominal_seen<='0';previous_local_locked<='0';halt<='0';
      previous_write<='0';previous_commit<='0';previous_start<='0';previous_snapshot<='0';previous_ack<='0';
    else
      if write_i='1' and previous_write='0' then
        if to_integer(address_i)<C_WORDS then
          -- Each unrolled word has a constant mask, so reserved bits are
          -- constant zero in both banks and their read muxes disappear.
          for word in 0 to C_WORDS-1 loop
            if address_i=to_unsigned(word,16) then
              if (write_data_i and not csr_mask(word))=x"0000000000000000" then
                shadow(word)<=write_data_i and csr_mask(word);
              else config_error<='1';end if;
            end if;
          end loop;
        else config_error<='1';end if;
      end if;
      if commit_i='1' and previous_commit='0' then
        n:=to_integer(unsigned(shadow(0)(15 downto 0)));p:=to_integer(unsigned(shadow(1)(23 downto 0)));
        w:=to_integer(unsigned(shadow(3)(9 downto 0)));
        valid_cfg:=idle='1' and role_i<3 and n>=3 and n<=G_MAX_NODES and n<=3*G_CAPACITY and p>=626
          and unsigned(shadow(1)(47 downto 32))/=0 and w>=1 and w<=625
          and unsigned(shadow(6)(63 downto 32))/=0 and unsigned(shadow(6)(31 downto 0))/=0;
        dt:=to_integer(unsigned(shadow(3)(23 downto 16)));
        if (to_unsigned(dt,9) and to_unsigned(dt+1,9))/=0 then valid_cfg:=false;end if;
        for i in 0 to G_CAPACITY-1 loop
          if unsigned(shadow(16+4*i))<x"00000000FFBE76C9" or unsigned(shadow(16+4*i))>x"0000000100418937"
            or unsigned(shadow(18+4*i)(11 downto 0))=0 or unsigned(shadow(18+4*i)(27 downto 16))=0 then valid_cfg:=false;end if;
        end loop;
        if valid_cfg then
          active<=shadow;nodes<=n;board<=to_integer(role_i);configured<='1';config_error<='0';state_reset<='1';
          page_id<=(others=>'0');missed<=(others=>'0');sample_age<=(others=>'0');measuring<='0';nominal_seen<='0';elapsed<=(others=>'0');halt<='0';
        else config_error<='1';end if;
      end if;
      if start_i='1' and previous_start='0' and configured='1' and idle='1' then start<='1';halt<='0';end if;
      if stop_i='1' then halt<='1';end if;
      -- Only the anchor receives JTAG START. Followers begin snapshots at the
      -- first local lock; the event journal already records the earlier frames.
      -- A lock EDGE avoids restarting collection on a late ACK after STOP.
      if configured='1' and measuring='0' and stop_i='0' and
        ((start_i='1' and previous_start='0' and idle='1') or (halt='0' and previous_local_locked='0' and locked(0)='1')) then
        measuring<='1';elapsed<=(others=>'0');nominal_seen<='0';sample_age<=(others=>'0');
      end if;
      if measuring='1' then
        if all_running='1' then nominal_seen<='1';end if;
        if nominal_seen='1' then elapsed<=elapsed+1;end if;
        if nominal_seen='1' and unsigned(active(7))/=0 and elapsed>=unsigned(active(7)) then halt<='1';measuring<='0';end if;
        if stop_i='1' then measuring<='0';end if;
        if sample_age+1>=unsigned(active(6)(63 downto 32)) then sample_age<=(others=>'0');
        else sample_age<=sample_age+1;end if;
      end if;
      if do_sample then
        if capture_ready='0' then missed<=missed+1;
        else
          page_id<=page_id+1;
          page(0)<=x"5054504500010001";page(1)<=active(4);page(2)<=active(5);page(3)<=raw;
          page(4)<=std_logic_vector(page_id+1)&std_logic_vector(to_unsigned(nodes,16))&std_logic_vector(to_unsigned(first,16));
          page(5)<=std_logic_vector(capture_lost)&std_logic_vector(missed);
          page(6)<=std_logic_vector(to_unsigned(capture_count,32))&std_logic_vector(to_unsigned(count,32));
          page(7)<=active(6);
          for i in 0 to G_CAPACITY-1 loop
            page(8+16*i)<=times(i);page(9+16*i)<=corrections(i);page(10+16*i)<=theta(i);page(11+16*i)<=delays(i);
            page(12+16*i)<=ages(i);page(13+16*i)<=accepted(i)&rejected(i);page(14+16*i)<=deferred(i)&skipped(i);
            page(15+16*i)<=indices(i);page(16+16*i)<=x"0000000"&errors(i)&holdover(i)&locked(i)&running(i)&backsteps(i);
            page(17+16*i)<=x"00000000"&dropped(i);
            for j in 10 to 15 loop page(8+16*i+j)<=(others=>'0');end loop;
          end loop;
        end if;
      end if;
    end if;
  end if;end process;
end;
