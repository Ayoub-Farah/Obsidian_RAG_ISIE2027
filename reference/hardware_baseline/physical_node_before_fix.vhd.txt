-- One physical endpoint. All sizes/mode/H are runtime registers.
-- The RX FIFO is independent of TX arbitration; no Aurora RX ready is assumed.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.benchmark_pkg.all;
use work.physical_pkg.all;

entity physical_node is
  generic(G_FIFO_DEPTH:positive:=8192);
  port(clk_i,rst_i:in std_logic; raw_i:in ticks_t;
    config_i:in config_t;board_i:in unsigned(1 downto 0);
    start_i:in std_logic;run_i,trial_i:in std_logic_vector(31 downto 0);
    rx_data_i:in std_logic_vector(15 downto 0);rx_keep_i:in std_logic_vector(1 downto 0);
    rx_valid_i,rx_last_i:in std_logic;rx_stamp_i:in ticks_t;
    tx_data_o:out std_logic_vector(15 downto 0);tx_keep_o:out std_logic_vector(1 downto 0);
    tx_valid_o,tx_last_o:out std_logic;tx_ready_i:in std_logic;
    idle_o,fault_o:out std_logic;removed_o:out std_logic;
    removed_origin_o:out unsigned(1 downto 0);removed_hops_o:out unsigned(15 downto 0);
    removed_bad_o:out std_logic;
    event_tx_o,event_rx_o:out event_t;event_tx_valid_o,event_rx_valid_o:out std_logic;
    summary_o:out summary_t);
end;

architecture rtl of physical_node is
  -- At most three packets exist globally; four descriptors include headroom.
  constant C_DESC:positive:=4;
  type descriptor_t is record
    ready,complete,sink,bad:std_logic;
    origin:unsigned(1 downto 0);
    remaining,hop:unsigned(15 downto 0);
    out_hcrc:std_logic_vector(15 downto 0);
    rx_first,rx_last:ticks_t;
  end record;
  constant C_EMPTY:descriptor_t:=('0','0','0','0',(others=>'0'),(others=>'0'),(others=>'0'),(others=>'0'),(others=>'0'),(others=>'0'));
  type descriptors_t is array(0 to C_DESC-1) of descriptor_t;
  signal desc:descriptors_t:=(others=>C_EMPTY);
  signal dh,dt:natural range 0 to C_DESC-1:=0;
  signal dc:natural range 0 to C_DESC:=0;
  signal fi,fo:std_logic_vector(17 downto 0);
  signal fv,fr,fe,fault_fifo:std_logic;
  signal level,highwater:unsigned(15 downto 0):=(others=>'0');
  signal rx_pos:natural range 0 to 8191:=0;
  signal rx_active,rx_bad,fault:std_logic:='0';
  signal rx_c32:std_logic_vector(31 downto 0):=x"FFFFFFFF";
  signal rx_hcrc,rx_ohcrc:std_logic_vector(15 downto 0):=x"FFFF";
  signal header:byte_array_t(0 to 31):=(others=>(others=>'0'));
  signal run_id,trial_id:std_logic_vector(31 downto 0):=(others=>'0');
  signal pending:std_logic:='0';
  -- owner 0=none, 1=local injection, 2=relay. It is held through gaps/stalls.
  signal owner:natural range 0 to 2:=0;
  signal tx_pos:natural range 0 to 8191:=0;
  signal tx_c32,next_c32:std_logic_vector(31 downto 0):=x"FFFFFFFF";
  signal tx_hcrc,next_hcrc:std_logic_vector(15 downto 0):=x"FFFF";
  signal txd:std_logic_vector(15 downto 0);signal txk:std_logic_vector(1 downto 0);
  signal txv,txl,sink_pop:std_logic;
  signal tx_first,tx_last,rx_first,rx_last,scheduled,retired_first,retired_last:ticks_t:=(others=>'1');
  signal stalls,queue_wait,relays,rx_frames,tx_words,rx_words,crc_errors,pattern_errors:ticks_t:=(others=>'0');
  signal retire_origin:unsigned(1 downto 0):=(others=>'0');
  signal retire_hops:unsigned(15 downto 0):=(others=>'0');
  signal trial_bad:std_logic:='0';
  signal own_stalls,relay_stalls,own_launch_wait,relay_residence:ticks_t:=(others=>'0');
  function advance(i:natural) return natural is begin if i=C_DESC-1 then return 0;else return i+1;end if;end;
  function observed_hop(c:config_t;board,hop:natural) return natural is
  begin if cfg_mode(c)=C_CT then if board=0 then return 3;else return board;end if;else return hop;end if;end;
begin
  fi<=rx_last_i & rx_keep_i(0) & rx_data_i;
  fifo:entity work.physical_fifo generic map(G_FIFO_DEPTH,18)
    port map(clk_i,rst_i,fi,rx_valid_i,fo,fv,fr,fe,fault_fifo,level);
  fault_o<=fault or fault_fifo;
  idle_o<='1' when owner=0 and pending='0' and rx_active='0' and dc=0 and fe='1' else '0';
  tx_data_o<=txd;tx_keep_o<=txk;tx_valid_o<=txv;tx_last_o<=txl;
  sink_pop<='1' when dc>0 and desc(dh).ready='1' and desc(dh).sink='1' and fv='1' else '0';
  fr<=sink_pop or (txv and tx_ready_i) when owner=2 else sink_pop;

  -- Two byte CRC datapath. In a mixed payload/CRC beat the first byte is
  -- incorporated before the CRC byte is selected. No trailer byte is offered
  -- until the independent incoming verdict is available.
  process(all)
    variable b:byte_t;variable word:std_logic_vector(15 downto 0);
    variable c:std_logic_vector(31 downto 0);variable h:std_logic_vector(15 downto 0);
    variable trailer:std_logic_vector(31 downto 0);
    variable pos,body_end,full,n,board,slot,rem_v,hop_v:natural;
    variable valid,last,bad:std_logic;variable keep:std_logic_vector(1 downto 0);
  begin
    c:=tx_c32;h:=tx_hcrc;word:=(others=>'0');valid:='0';last:='0';keep:="11";
    body_end:=C_HEADER_BYTES+cfg_payload(config_i);full:=body_end+4;board:=to_integer(board_i);slot:=cfg_slot(config_i);
    bad:='0';rem_v:=0;hop_v:=0;
    if owner=1 then
      valid:='1';if tx_pos+2>=full then last:='1';end if;
      if tx_pos+1=full then keep:="10";end if;
    elsif owner=2 then
      valid:=fv;last:=fo(17);keep:='1' & fo(16);bad:=desc(dh).bad;
      rem_v:=to_integer(desc(dh).remaining);hop_v:=to_integer(desc(dh).hop);
      if tx_pos+1>=body_end and desc(dh).complete='0' then valid:='0';end if;
    end if;
    n:=2;if keep="10" then n:=1;end if;
    for j in 0 to 1 loop
      pos:=tx_pos+j;b:=x"00";
      if owner=1 then
        if pos<30 then b:=header_byte(config_i,run_id,trial_id,board,pos);
        elsif pos=30 then b:=h(15 downto 8);elsif pos=31 then b:=h(7 downto 0);
        elsif pos<body_end then b:=payload_byte(config_i,board,trial_id,pos-C_HEADER_BYTES);end if;
      elsif owner=2 then
        if j=0 then b:=fo(15 downto 8);else b:=fo(7 downto 0);end if;
        if cfg_mode(config_i)=C_RAG then
          if pos=24 then b:=std_logic_vector(to_unsigned((rem_v-1)/256,8));
          elsif pos=25 then b:=std_logic_vector(to_unsigned((rem_v-1) mod 256,8));
          elsif pos=26 then b:=std_logic_vector(to_unsigned((hop_v+1)/256,8));
          elsif pos=27 then b:=std_logic_vector(to_unsigned((hop_v+1) mod 256,8));end if;
        end if;
        if pos=30 then b:=desc(dh).out_hcrc(15 downto 8);
        elsif pos=31 then b:=desc(dh).out_hcrc(7 downto 0);end if;
        if cfg_mode(config_i)=C_CT and pos>=C_HEADER_BYTES+board*slot and pos<C_HEADER_BYTES+(board+1)*slot then
          b:=data_pattern(board,trial_id,pos-C_HEADER_BYTES-board*slot);
        end if;
      end if;
      if j<n then
        if pos>=body_end and pos<body_end+4 then
          trailer:=not c;if bad='1' then trailer(0):=not trailer(0);end if;
          b:=trailer(8*(pos-body_end)+7 downto 8*(pos-body_end));
        elsif pos<body_end then c:=crc32_byte(c,b);end if;
        if pos<30 then h:=crc16_byte(h,b);end if;
      end if;
      if j=0 then word(15 downto 8):=b;else word(7 downto 0):=b;end if;
    end loop;
    txd<=word;txk<=keep;txv<=valid;txl<=last;next_c32<=c;next_hcrc<=h;
  end process;

  process(all)
    variable s:summary_t;
  begin
    s:=(others=>'0');s(159 downto 0):=config_i;
    s(191 downto 160):=run_id;s(223 downto 192):=trial_id;
    s(225 downto 224):=std_logic_vector(board_i);s(226):=trial_bad;s(227):=fault or fault_fifo;
    s(239 downto 228):=(others=>'0');s(241 downto 240):=std_logic_vector(retire_origin);
    s(271 downto 256):=std_logic_vector(retire_hops);
    s(335 downto 272):=std_logic_vector(scheduled);
    s(399 downto 336):=std_logic_vector(tx_first);s(463 downto 400):=std_logic_vector(tx_last);
    s(527 downto 464):=std_logic_vector(retired_first);s(591 downto 528):=std_logic_vector(retired_last);
    s(655 downto 592):=std_logic_vector(stalls);s(719 downto 656):=std_logic_vector(queue_wait);
    s(783 downto 720):=std_logic_vector(relays);s(847 downto 784):=std_logic_vector(rx_frames);
    s(911 downto 848):=std_logic_vector(tx_words);s(975 downto 912):=std_logic_vector(rx_words);
    s(1039 downto 976):=std_logic_vector(crc_errors);s(1103 downto 1040):=std_logic_vector(pattern_errors);
    s(1119 downto 1104):=std_logic_vector(highwater);
    s(1791 downto 1728):=std_logic_vector(own_stalls);s(1855 downto 1792):=std_logic_vector(relay_stalls);
    s(1919 downto 1856):=std_logic_vector(own_launch_wait);s(1983 downto 1920):=std_logic_vector(relay_residence);
    summary_o<=s;
  end process;

  process(clk_i)
    variable count,head,tail,n,pos,p,s,board,origin,remaining,hop,slot_index:natural;
    variable c:std_logic_vector(31 downto 0);variable hc,oh:std_logic_vector(15 downto 0);
    variable h:byte_array_t(0 to 31);variable b,ob,expected:byte_t;
    variable bad,header_bad,pattern_bad,crc_bad:std_logic;
    variable dd:descriptor_t;variable fifo_last:boolean;
  begin if rising_edge(clk_i) then
    removed_o<='0';event_tx_valid_o<='0';event_rx_valid_o<='0';
    if rst_i='1' then
      desc<=(others=>C_EMPTY);dh<=0;dt<=0;dc<=0;rx_active<='0';rx_pos<=0;rx_bad<='0';
      owner<=0;pending<='0';tx_pos<=0;fault<='0';highwater<=(others=>'0');trial_bad<='0';
      rx_c32<=x"FFFFFFFF";rx_hcrc<=x"FFFF";rx_ohcrc<=x"FFFF";tx_c32<=x"FFFFFFFF";tx_hcrc<=x"FFFF";
      stalls<=(others=>'0');queue_wait<=(others=>'0');relays<=(others=>'0');rx_frames<=(others=>'0');
      tx_words<=(others=>'0');rx_words<=(others=>'0');crc_errors<=(others=>'0');pattern_errors<=(others=>'0');
      own_stalls<=(others=>'0');relay_stalls<=(others=>'0');own_launch_wait<=(others=>'0');relay_residence<=(others=>'0');
    else
      count:=dc;head:=dh;tail:=dt;p:=cfg_payload(config_i);s:=cfg_slot(config_i);board:=to_integer(board_i);
      if level>highwater then highwater<=level;end if;
      if fault_fifo='1' then fault<='1';trial_bad<='1';end if;
      if start_i='1' then
        assert dc=0 and owner=0 and rx_active='0' report "Start before physical node drain" severity failure;
        run_id<=run_i;trial_id<=trial_i;scheduled<=raw_i;
        if cfg_mode(config_i)=C_RAG or board=0 then pending<='1';end if;
        tx_first<=(others=>'1');tx_last<=(others=>'1');retired_first<=(others=>'1');retired_last<=(others=>'1');
        stalls<=(others=>'0');queue_wait<=(others=>'0');relays<=(others=>'0');rx_frames<=(others=>'0');
        tx_words<=(others=>'0');rx_words<=(others=>'0');crc_errors<=(others=>'0');pattern_errors<=(others=>'0');
        highwater<=(others=>'0');trial_bad<='0';retire_hops<=(others=>'0');
        own_stalls<=(others=>'0');relay_stalls<=(others=>'0');own_launch_wait<=(others=>'0');relay_residence<=(others=>'0');
      end if;
      if owner=0 then
        tx_pos<=0;tx_c32<=x"FFFFFFFF";tx_hcrc<=x"FFFF";
        if pending='1' then owner<=1;pending<='0';
        elsif dc>0 and desc(dh).ready='1' and desc(dh).sink='0' then owner<=2;end if;
      end if;
      if txv='1' and tx_ready_i='0' then
        stalls<=stalls+1;
        if tx_pos>0 then if owner=1 then own_stalls<=own_stalls+1;else relay_stalls<=relay_stalls+1;end if;end if;
      end if;
      if pending='1' then queue_wait<=queue_wait+1;
      elsif dc>0 and desc(dh).ready='1' and desc(dh).sink='0' and owner/=2 then queue_wait<=queue_wait+1;end if;
      if txv='1' and tx_ready_i='1' then
        tx_words<=tx_words+1;tx_c32<=next_c32;tx_hcrc<=next_hcrc;
        if tx_pos=0 then
          event_tx_valid_o<='1';
          if owner=1 then
            tx_first<=raw_i;own_launch_wait<=raw_i-scheduled;event_tx_o<=make_event(raw_i,trial_id,board,0,1);
          else
            relays<=relays+1;
            event_tx_o<=make_event(raw_i,trial_id,to_integer(desc(dh).origin),observed_hop(config_i,board,to_integer(desc(dh).hop)+1),3,desc(dh).bad);
            queue_wait<=queue_wait+(raw_i-desc(dh).rx_first);
            relay_residence<=relay_residence+(raw_i-desc(dh).rx_first);
          end if;
        end if;
        if txl='1' then
          event_tx_valid_o<='1';owner<=0;tx_pos<=0;
          if owner=1 then tx_last<=raw_i;event_tx_o<=make_event(raw_i,trial_id,board,0,2);
          else
            event_tx_o<=make_event(raw_i,trial_id,to_integer(desc(dh).origin),observed_hop(config_i,board,to_integer(desc(dh).hop)+1),4,desc(dh).bad);
            desc(dh).ready<='0';head:=advance(dh);if count>0 then count:=count-1;else fault<='1';end if;
          end if;
        elsif tx_pos<8190 then tx_pos<=tx_pos+2;else fault<='1';end if;
      end if;
      if sink_pop='1' then
        if fo(17)='1' then
          if desc(dh).complete='0' then fault<='1';end if;
          removed_o<='1';removed_origin_o<=desc(dh).origin;
          if cfg_mode(config_i)=C_CT then removed_hops_o<=to_unsigned(3,16);retire_hops<=to_unsigned(3,16);
          else removed_hops_o<=desc(dh).hop+1;retire_hops<=desc(dh).hop+1;end if;
          removed_bad_o<=desc(dh).bad;retire_origin<=desc(dh).origin;
          retired_first<=desc(dh).rx_first;retired_last<=desc(dh).rx_last;
          trial_bad<=trial_bad or desc(dh).bad;
          desc(dh).ready<='0';head:=advance(dh);if count>0 then count:=count-1;else fault<='1';end if;
        end if;
      end if;
      if rx_valid_i='1' then
        h:=header;c:=rx_c32;hc:=rx_hcrc;oh:=rx_ohcrc;bad:=rx_bad;pattern_bad:='0';
        dd:=desc(dt);pos:=rx_pos;rx_words<=rx_words+1;
        if rx_active='0' then
          pos:=0;bad:='0';c:=x"FFFFFFFF";hc:=x"FFFF";oh:=x"FFFF";dd:=C_EMPTY;
          dd.rx_first:=rx_stamp_i;rx_active<='1';
          if count=C_DESC then fault<='1';else count:=count+1;end if;
        end if;
        n:=2;if rx_keep_i="10" then n:=1;elsif rx_keep_i/="11" then bad:='1';end if;
        if rx_keep_i="10" and rx_last_i='0' then bad:='1';end if;
        -- Update header before examining the complete pair of remaining/hop.
        if pos<32 then h(pos):=rx_data_i(15 downto 8);if n=2 then h(pos+1):=rx_data_i(7 downto 0);end if;end if;
        remaining:=to_integer(unsigned(std_logic_vector'(h(24)&h(25))));
        hop:=to_integer(unsigned(std_logic_vector'(h(26)&h(27))));
        for j in 0 to 1 loop
          if j<n then
            if j=0 then b:=rx_data_i(15 downto 8);else b:=rx_data_i(7 downto 0);end if;
            c:=crc32_byte(c,b);ob:=b;
            if pos+j<30 then
              hc:=crc16_byte(hc,b);
              if cfg_mode(config_i)=C_RAG and remaining>1 then
                if pos+j=24 then ob:=std_logic_vector(to_unsigned((remaining-1)/256,8));
                elsif pos+j=25 then ob:=std_logic_vector(to_unsigned((remaining-1) mod 256,8));end if;
              end if;
              if cfg_mode(config_i)=C_RAG then
                if pos+j=26 then ob:=std_logic_vector(to_unsigned(((hop+1)/256) mod 256,8));
                elsif pos+j=27 then ob:=std_logic_vector(to_unsigned((hop+1) mod 256,8));end if;
              end if;
              oh:=crc16_byte(oh,ob);
            elsif pos+j>=32 and pos+j<32+p then
              origin:=to_integer(dd.origin);
              expected:=data_pattern(origin,trial_id,pos+j-32);
              if cfg_mode(config_i)=C_CT then
                if pos+j-32<3*s then
                  -- No runtime divider: three fixed reserved ranges.
                  slot_index:=0;
                  if pos+j-32>=2*s then slot_index:=2;elsif pos+j-32>=s then slot_index:=1;end if;
                  expected:=data_pattern(slot_index,trial_id,pos+j-32-slot_index*s);
                  if board>0 and slot_index>=board then expected:=x"00";end if;
                else expected:=data_pattern(3,trial_id,pos+j-32);end if;
              end if;
              if b/=expected then bad:='1';pattern_bad:='1';end if;
            end if;
          end if;
        end loop;
        if pos=30 then
          header_bad:='0';
          if hc/=h(30)&h(31) then header_bad:='1';end if;
          for j in 0 to 29 loop
            -- RAG hop/remaining and origin are the only variable header fields.
            if not (j=16 or (j>=24 and j<=27)) then
              if h(j)/=header_byte(config_i,run_id,trial_id,0,j) then header_bad:='1';end if;
            end if;
          end loop;
          origin:=to_integer(unsigned(h(16)));
          if origin>2 or remaining=0 or remaining>cfg_hops(config_i) then header_bad:='1';origin:=0;end if;
          if cfg_mode(config_i)=C_RAG and remaining+hop/=cfg_hops(config_i) then header_bad:='1';end if;
          if cfg_mode(config_i)=C_CT and (origin/=0 or hop/=0 or remaining/=cfg_hops(config_i)) then header_bad:='1';end if;
          dd.origin:=to_unsigned(origin,2);dd.remaining:=to_unsigned(remaining,16);dd.hop:=to_unsigned(hop,16);dd.out_hcrc:=oh;
          dd.ready:='1';dd.sink:='0';
          if header_bad='1' or (cfg_mode(config_i)=C_CT and board=0) or
            (cfg_mode(config_i)=C_RAG and remaining=1) then dd.sink:='1';end if;
          bad:=bad or header_bad;
          if header_bad='1' then fault<='1';end if;
          event_rx_valid_o<='1';event_rx_o<=make_event(dd.rx_first,trial_id,origin,observed_hop(config_i,board,hop+1),5,header_bad);
        end if;
        if pattern_bad='1' then pattern_errors<=pattern_errors+1;end if;
        if rx_last_i='1' then
          crc_bad:='0';if c/=x"DEBB20E3" then crc_bad:='1';crc_errors<=crc_errors+1;end if;
          if pos+n/=32+p+4 then bad:='1';fault<='1';end if;
          if pos<30 then dd.ready:='1';dd.sink:='1';bad:='1';fault<='1';end if;
          bad:=bad or crc_bad;dd.complete:='1';dd.bad:=bad;dd.rx_last:=rx_stamp_i;
          event_rx_valid_o<='1';event_rx_o<=make_event(rx_stamp_i,trial_id,to_integer(dd.origin),observed_hop(config_i,board,to_integer(dd.hop)+1),6,bad);
          rx_frames<=rx_frames+1;trial_bad<=trial_bad or bad;
          tail:=advance(dt);rx_active<='0';rx_pos<=0;rx_bad<='0';
        else
          if pos<8190 then rx_pos<=pos+2;else fault<='1';bad:='1';end if;
          dd.bad:=bad;rx_bad<=bad;
        end if;
        header<=h;desc(dt)<=dd;rx_c32<=c;rx_hcrc<=hc;rx_ohcrc<=oh;
      end if;
      dh<=head;dt<=tail;dc<=count;
    end if;
  end if;end process;
end;
