-- SPDX-License-Identifier: MIT
-- RAG is cut-through: routing starts after the 16-byte header, not after CRC32.
-- The input is a ready/valid INTERNAL stream; Aurora RX needs a capture FIFO.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.benchmark_pkg.all;

entity rag_node is
  generic (
    G_MODE:natural:=2; G_NODES:positive:=3; G_NODE_ID:natural:=0;
    G_DATA_BYTES:positive:=6; G_REF_BYTES:positive:=2;
    G_FIFO_WORDS:positive:=2048; G_MAX_FRAME_BYTES:positive:=4096;
    G_DESC_DEPTH:positive:=32; G_HEADER_DELAY_CYCLES:positive:=10;
    G_RUNTIME_CONFIG:boolean:=false
  );
  port (
    clk_i,rst_i,start_i:in std_logic;
    cycle_id_i:in std_logic_vector(31 downto 0);
    rx_data_i:in std_logic_vector(15 downto 0);
    rx_keep_i:in std_logic_vector(1 downto 0);
    rx_valid_i,rx_last_i:in std_logic; rx_ready_o:out std_logic;
    tx_data_o:out std_logic_vector(15 downto 0);
    tx_keep_o:out std_logic_vector(1 downto 0);
    tx_valid_o,tx_last_o:out std_logic; tx_ready_i:in std_logic;
    useful_o,drained_o,error_o:out std_logic;
    crc_errors_o:out std_logic_vector(31 downto 0);
    fifo_highwater_o:out std_logic_vector(15 downto 0);
    first_tx_o,first_rx_o:out std_logic;
    data_addr_i:in std_logic_vector(15 downto 0);
    data_byte_o:out std_logic_vector(7 downto 0);
    config_mode_i:in natural range 0 to 2:=G_MODE;
    config_nodes_i:in positive range 1 to G_NODES:=G_NODES;
    config_id_i:in natural range 0 to G_NODES-1:=G_NODE_ID;
    returned_o:out std_logic:='0' 
  );
end entity;

architecture rtl of rag_node is
  signal mode_cfg:natural range 0 to 2:=G_MODE;
  signal nodes_cfg:positive range 1 to G_NODES:=G_NODES;
  signal id_cfg:natural range 0 to G_NODES-1:=G_NODE_ID;
  signal local_kind:natural range 1 to 2;
  signal payload_size:natural range 1 to G_NODES*G_REF_BYTES+G_DATA_BYTES;
  signal body_size,byte_count,word_count:natural range 1 to G_NODES*G_REF_BYTES+G_DATA_BYTES+20;
  function local_kind_static return natural is
  begin if G_MODE=0 and G_NODE_ID=0 then return 2; else return 1; end if; end;
  function local_payload return natural is
  begin if G_MODE=0 and G_NODE_ID=0 then return G_NODES*G_REF_BYTES; else return G_DATA_BYTES; end if; end;
  function advance(p,n:natural) return natural is
  begin if p=n-1 then return 0; else return p+1; end if; end;
  constant C_PAYLOAD:natural:=local_payload;
  constant C_BODY:natural:=16+C_PAYLOAD;
  constant C_BYTES:natural:=20+C_PAYLOAD;
  constant C_WORDS:natural:=(C_BYTES+1)/2;
  type fifo_data_t is array(0 to G_FIFO_WORDS-1) of std_logic_vector(15 downto 0);
  type fifo_keep_t is array(0 to G_FIFO_WORDS-1) of std_logic_vector(1 downto 0);
  signal words:fifo_data_t; signal keeps:fifo_keep_t;
  signal lasts:std_logic_vector(0 to G_FIFO_WORDS-1);
  signal wr_ptr,rd_ptr:natural range 0 to G_FIFO_WORDS-1:=0;
  signal used:natural range 0 to G_FIFO_WORDS:=0;
  signal highwater:natural range 0 to G_FIFO_WORDS:=0;
  type release_array_t is array(0 to G_DESC_DEPTH-1) of unsigned(63 downto 0);
  signal desc_release:release_array_t:=(others=>(others=>'0'));
  signal ticks:unsigned(63 downto 0):=(others=>'0');
  signal desc_ready,desc_forward:std_logic_vector(0 to G_DESC_DEPTH-1):=(others=>'0');
  signal desc_wr,desc_rd,rx_desc:natural range 0 to G_DESC_DEPTH-1:=0;
  signal desc_count:natural range 0 to G_DESC_DEPTH:=0;
  signal rx_active:std_logic:='0';
  signal rx_index:natural range 0 to G_MAX_FRAME_BYTES+2:=0;
  signal header:byte_array_t(0 to 15):=(others=>(others=>'0'));
  signal rx_hcrc:std_logic_vector(15 downto 0):=x"FFFF";
  signal rx_crc,rx_trailer:std_logic_vector(31 downto 0):=(others=>'0');
  signal rx_kind:natural range 0 to 255:=0;
  signal rx_origin:natural range 0 to 65535:=0;
  signal rx_payload:natural range 0 to 65535:=0;
  signal rx_header_good,rx_packet_good:std_logic:='0';
  signal active_mask:std_logic_vector(G_NODES-1 downto 0);
  signal bitmap:std_logic_vector(G_NODES-1 downto 0):=(others=>'0');
  signal table_data:byte_array_t(0 to G_NODES*G_DATA_BYTES-1);
  signal reference_seen,own_return,started,local_active,local_done:std_logic:='0';
  signal local_index:natural range 0 to (20+G_NODES*G_REF_BYTES+G_DATA_BYTES+1)/2:=0;
  signal local_crc:std_logic_vector(31 downto 0):=x"FFFFFFFF";
  signal local_crc_next:std_logic_vector(31 downto 0);
  signal local_header:byte_array_t(0 to 15);
  signal current_cycle:std_logic_vector(31 downto 0):=(others=>'0');
  signal error_reg,rx_seen:std_logic:='0';
  signal crc_errors:unsigned(31 downto 0):=(others=>'0');
  signal relay_word,drop_word:std_logic;
  signal useful,drained:std_logic;
begin
  mode_cfg<=config_mode_i when G_RUNTIME_CONFIG else G_MODE;
  nodes_cfg<=config_nodes_i when G_RUNTIME_CONFIG else G_NODES;
  id_cfg<=config_id_i when G_RUNTIME_CONFIG else G_NODE_ID;
  local_kind<=2 when mode_cfg=0 and id_cfg=0 else 1;
  payload_size<=nodes_cfg*G_REF_BYTES when local_kind=2 else G_DATA_BYTES;
  body_size<=16+payload_size;byte_count<=20+payload_size;word_count<=(21+payload_size)/2;
  process(all) begin
    for i in active_mask'range loop
      if i<nodes_cfg then active_mask(i)<='1';else active_mask(i)<='0';end if;
    end loop;
  end process;
  returned_o<=own_return;
  assert mode_cfg=0 or mode_cfg=2 report "rag_node accepts RAG_C=0 or RAG_D=2" severity failure;
  assert G_NODE_ID<G_NODES and G_NODES<65536 severity failure;
  assert byte_count<=G_MAX_FRAME_BYTES and payload_size<65536 severity failure;
  assert G_NODES*G_DATA_BYTES<65536 and (mode_cfg=2 or nodes_cfg*G_REF_BYTES+20<=G_MAX_FRAME_BYTES) severity failure;
  assert G_HEADER_DELAY_CYCLES>=10 report "Header routing delay must be >=10 cycles" severity failure;
  assert G_FIFO_WORDS>=8 and G_FIFO_WORDS<=65535 severity failure;

  local_header<=make_header(local_kind,id_cfg,nodes_cfg,payload_size,current_cycle);
  rx_ready_o<='1' when cycle_id_i=current_cycle and used<G_FIFO_WORDS and (rx_active='1' or desc_count<G_DESC_DEPTH) else '0';
  relay_word<='1' when local_active='0' and local_done='1' and desc_count>0 and
                          desc_ready(desc_rd)='1' and ticks>=desc_release(desc_rd) and desc_forward(desc_rd)='1' and used>0 else '0';
  drop_word<='1' when local_active='0' and local_done='1' and desc_count>0 and
                         desc_ready(desc_rd)='1' and ticks>=desc_release(desc_rd) and desc_forward(desc_rd)='0' and used>0 else '0';
  useful<='1' when error_reg='0' and started='1' and
    ((mode_cfg=2 and bitmap=active_mask) or
     (mode_cfg=0 and id_cfg=0 and bitmap=active_mask) or
     (mode_cfg=0 and id_cfg/=0 and reference_seen='1' and local_done='1')) else '0';
  drained<='1' when useful='1' and local_done='1' and used=0 and desc_count=0 and rx_active='0' and
    ((mode_cfg=0 and id_cfg/=0) or own_return='1') else '0';
  useful_o<=useful;drained_o<=drained;error_o<=error_reg;
  crc_errors_o<=std_logic_vector(crc_errors);
  fifo_highwater_o<=std_logic_vector(to_unsigned(highwater,16));
  data_byte_o<=table_data(to_integer(unsigned(data_addr_i))) when to_integer(unsigned(data_addr_i))<nodes_cfg*G_DATA_BYTES else (others=>'0');

  -- Both CRC bytes and odd-byte word boundaries are computed from the CRC
  -- after the preceding body byte in THIS beat, then held during TX stalls.
  process(all)
    variable d:std_logic_vector(15 downto 0);
    variable c,final_crc:std_logic_vector(31 downto 0);
    variable b:byte_t;variable pos,j:natural;
  begin
    tx_data_o<=(others=>'0');tx_keep_o<="11";tx_valid_o<='0';tx_last_o<='0';
    d:=(others=>'0');c:=local_crc;
    if local_active='1' then
      for lane in 0 to 1 loop
        pos:=2*local_index+lane;b:=(others=>'0');
        if pos<16 then b:=local_header(pos);c:=crc32_byte(c,b);
        elsif pos<body_size then
          j:=pos-16;
          if local_kind=2 then b:=ref_pattern(j/G_REF_BYTES,current_cycle,j mod G_REF_BYTES);
          else b:=data_pattern(id_cfg,current_cycle,j);end if;
          c:=crc32_byte(c,b);
        elsif pos<byte_count then
          final_crc:=not c;j:=pos-body_size;b:=final_crc(8*j+7 downto 8*j);
        end if;
        if lane=0 then d(15 downto 8):=b;else d(7 downto 0):=b;end if;
      end loop;
      tx_data_o<=d;tx_valid_o<='1';
      if local_index=word_count-1 then
        tx_last_o<='1';if byte_count mod 2=1 then tx_keep_o<="10";end if;
      end if;
    elsif relay_word='1' then
      tx_data_o<=words(rd_ptr);tx_keep_o<=keeps(rd_ptr);tx_last_o<=lasts(rd_ptr);tx_valid_o<='1';
    end if;
    local_crc_next<=c;
  end process;

  process(clk_i)
    variable unext,dnext:natural;
    variable idx,di,ki,orig,plen,off,nbytes:natural;
    variable h:byte_array_t(0 to 15);
    variable hc:std_logic_vector(15 downto 0);
    variable c,tr:std_logic_vector(31 downto 0);
    variable b:byte_t;variable hg,pg,route,valid_last:boolean;
    variable rx_cycle:std_logic_vector(31 downto 0);
  begin
    if rising_edge(clk_i) then
      first_tx_o<='0';first_rx_o<='0';ticks<=ticks+1;
      if rst_i='1' then
        wr_ptr<=0;rd_ptr<=0;used<=0;highwater<=0;ticks<=(others=>'0');
        desc_wr<=0;desc_rd<=0;desc_count<=0;desc_ready<=(others=>'0');desc_forward<=(others=>'0');
        rx_active<='0';rx_index<=0;bitmap<=(others=>'0');reference_seen<='0';own_return<='0';
        started<='0';local_active<='0';local_done<='0';local_index<=0;local_crc<=x"FFFFFFFF";
        current_cycle<=cycle_id_i;error_reg<='0';rx_seen<='0';crc_errors<=(others=>'0');
      elsif cycle_id_i/=current_cycle then
        -- ARM/the scheduler must present a new cycle before any frame of it.
        -- Never silently accept overlapping transactions.
        if used/=0 or rx_active='1' or local_active='1' or (started='1' and drained='0') then
          error_reg<='1';
        else
          current_cycle<=cycle_id_i;bitmap<=(others=>'0');reference_seen<='0';own_return<='0';
          started<=start_i;local_active<=start_i;local_done<='0';local_index<=0;local_crc<=x"FFFFFFFF";
          if start_i='1' then
            bitmap(id_cfg)<='1';
            for j in 0 to G_DATA_BYTES-1 loop table_data(id_cfg*G_DATA_BYTES+j)<=data_pattern(id_cfg,cycle_id_i,j);end loop;
          end if;
          error_reg<='0';rx_seen<='0';highwater<=0;
        end if;
      else
        unext:=used;dnext:=desc_count;
        if start_i='1' then
          if started='1' then error_reg<='1';
          else
            started<='1';local_active<='1';local_done<='0';local_index<=0;local_crc<=x"FFFFFFFF";
            bitmap(id_cfg)<='1';
            for j in 0 to G_DATA_BYTES-1 loop table_data(id_cfg*G_DATA_BYTES+j)<=data_pattern(id_cfg,current_cycle,j);end loop;
          end if;
        end if;
        if local_active='1' and tx_ready_i='1' then
          if local_index=0 then first_tx_o<='1';end if;
          local_crc<=local_crc_next;
          if local_index=word_count-1 then local_active<='0';local_done<='1';
          else local_index<=local_index+1;end if;
        end if;
        if (relay_word='1' and tx_ready_i='1') or drop_word='1' then
          unext:=unext-1;rd_ptr<=advance(rd_ptr,G_FIFO_WORDS);
          if lasts(rd_ptr)='1' then
            desc_ready(desc_rd)<='0';desc_rd<=advance(desc_rd,G_DESC_DEPTH);dnext:=dnext-1;
          end if;
        end if;

        if rx_valid_i='1' and rx_ready_o='1' then
          words(wr_ptr)<=rx_data_i;keeps(wr_ptr)<=rx_keep_i;lasts(wr_ptr)<=rx_last_i;
          wr_ptr<=advance(wr_ptr,G_FIFO_WORDS);unext:=unext+1;
          if rx_seen='0' then rx_seen<='1';first_rx_o<='1';end if;
          h:=header;hc:=rx_hcrc;c:=rx_crc;tr:=rx_trailer;
          idx:=rx_index;di:=rx_desc;ki:=rx_kind;orig:=rx_origin;plen:=rx_payload;
          hg:=rx_header_good='1';pg:=rx_packet_good='1';
          if rx_active='0' then
            rx_active<='1';idx:=0;di:=desc_wr;rx_desc<=desc_wr;desc_wr<=advance(desc_wr,G_DESC_DEPTH);dnext:=dnext+1;
            desc_ready(di)<='0';desc_forward(di)<='0';desc_release(di)<=ticks+G_HEADER_DELAY_CYCLES;
            hc:=x"FFFF";c:=x"FFFFFFFF";tr:=(others=>'0');hg:=false;pg:=true;ki:=0;orig:=0;plen:=0;
          end if;
          nbytes:=2;
          if rx_keep_i="10" and rx_last_i='1' then nbytes:=1;
          elsif rx_keep_i/="11" then pg:=false;error_reg<='1';end if;
          for lane in 0 to 1 loop
            if lane<nbytes then
              if lane=0 then b:=rx_data_i(15 downto 8);else b:=rx_data_i(7 downto 0);end if;
              if idx<14 then hc:=crc16_byte(hc,b);end if;
              if idx<16 then h(idx):=b;end if;
              if idx=15 then
                ki:=to_integer(unsigned(h(3)));orig:=to_integer(unsigned(std_logic_vector'(h(4)&h(5))));
                plen:=to_integer(unsigned(std_logic_vector'(h(12)&h(13))));rx_cycle:=h(8)&h(9)&h(10)&h(11);
                hg:=pg and h(0)=x"C3" and h(1)=x"5A" and h(2)=x"01" and
                    (h(14)&h(15))=hc and to_integer(unsigned(std_logic_vector'(h(6)&h(7))))=nodes_cfg and
                    orig<nodes_cfg and rx_cycle=current_cycle and plen+20<=G_MAX_FRAME_BYTES;
                if ki=1 then
                  hg:=hg and plen=G_DATA_BYTES;
                  if mode_cfg=0 then hg:=hg and orig/=0;end if;
                elsif ki=2 then hg:=hg and mode_cfg=0 and orig=0 and plen=nodes_cfg*G_REF_BYTES;
                else hg:=false;end if;
                route:=hg and not ((ki=1 and mode_cfg=0 and id_cfg=0) or
                                     (ki=1 and mode_cfg=2 and orig=id_cfg) or
                                     (ki=2 and id_cfg=0));
                desc_ready(di)<='1';if route then desc_forward(di)<='1';else desc_forward(di)<='0';end if;
                if not hg then pg:=false;error_reg<='1';end if;
              end if;
              if idx<16 or idx<16+plen then c:=crc32_byte(c,b);
              elsif idx<20+plen then off:=idx-(16+plen);tr(8*off+7 downto 8*off):=b;
              else pg:=false;end if;
              if hg and idx>=16 and idx<16+plen then
                off:=idx-16;
                if ki=1 then
                  if b/=data_pattern(orig,current_cycle,off) then pg:=false;end if;
                  table_data(orig*G_DATA_BYTES+off)<=b;
                elsif ki=2 then
                  if b/=ref_pattern(off/G_REF_BYTES,current_cycle,off mod G_REF_BYTES) then pg:=false;end if;
                end if;
              end if;
              if idx<G_MAX_FRAME_BYTES+2 then idx:=idx+1;else pg:=false;end if;
            end if;
          end loop;
          header<=h;rx_hcrc<=hc;rx_crc<=c;rx_trailer<=tr;
          rx_kind<=ki;rx_origin<=orig;rx_payload<=plen;rx_index<=idx;
          if hg then rx_header_good<='1';else rx_header_good<='0';end if;
          if pg then rx_packet_good<='1';else rx_packet_good<='0';end if;
          if rx_last_i='1' then
            rx_active<='0';rx_index<=0;
            valid_last:=hg and pg and idx=plen+20 and tr=(not c);
            if valid_last then
              if ki=1 then
                if mode_cfg=2 and orig=id_cfg then
                  if own_return='1' then error_reg<='1';else own_return<='1';end if;
                elsif bitmap(orig)='1' then error_reg<='1';
                else bitmap(orig)<='1';end if;
              elsif ki=2 then
                if reference_seen='1' then error_reg<='1';else reference_seen<='1';end if;
                if id_cfg=0 then own_return<='1';end if;
              end if;
            else
              error_reg<='1';if tr/=(not c) then crc_errors<=crc_errors+1;end if;
            end if;
            if idx<16 then desc_ready(di)<='1';desc_forward(di)<='0';end if;
          end if;
        end if;
        used<=unext;desc_count<=dnext;
        if unext>highwater then highwater<=unext;end if;
      end if;
    end if;
  end process;
end architecture;
