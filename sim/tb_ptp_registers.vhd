library ieee;use ieee.std_logic_1164.all;use ieee.numeric_std.all;use std.env.all;
entity tb_ptp_registers is end;
architecture test of tb_ptp_registers is
  signal clk:std_logic:='0';signal rst:std_logic:='1';
  signal addr:unsigned(15 downto 0):=(others=>'0');signal wd,rd,cid,obs:std_logic_vector(63 downto 0):=(others=>'0');
  signal wr,commit,start,stop_req,apply,snapshot,ack,ref,pin:std_logic:='0';
  signal shadow:unsigned(15 downto 0):=(others=>'0');signal status:std_logic_vector(255 downto 0);
begin
  clk<=not clk after 8 ns;
  u:entity work.ptp_emulation_system generic map(4,12,5000)
    port map(clk,rst,'1',addr,wd,wr,commit,start,stop_req,"01",shadow,apply,'1',snapshot,ack,rd,status,obs,cid,ref,pin,
      x"0000",x"0000","11","11",'0','0','0','0',open,open,open,open,open,open,open,open,'1','1');
  process
    variable original,raw_before:std_logic_vector(63 downto 0);
    procedure tick is begin wait until falling_edge(clk);end;
    procedure write_word(a:natural;v:std_logic_vector(63 downto 0)) is
    begin addr<=to_unsigned(a,16);wd<=v;tick;wr<='1';tick;wr<='0';tick;end;
    procedure apply_cfg is begin commit<='1';tick;commit<='0';tick;tick;end;
    procedure read_word(a:natural;expected:std_logic_vector(63 downto 0)) is
    begin addr<=to_unsigned(a,16);tick;assert rd=expected report "CSR readback mismatch at word "&integer'image(a) severity failure;end;
    procedure reject_reserved(a:natural;value,previous:std_logic_vector(63 downto 0)) is
    begin
      write_word(a,value);read_word(a,previous);read_word(16384+a,previous);
      assert status(1)='1' and status(0)='1' and status(2)='1' and cid=x"123456789ABCDEF0"
        report "Reserved write changed active configuration or did not report an error" severity failure;
      apply_cfg;assert status(1)='0' report "Valid commit did not clear reserved-write error" severity failure;
    end;
  begin
    tick;rst<='0';tick;
    write_word(0,x"000000000000000A");write_word(4,x"123456789ABCDEF0");
    apply_cfg;
    assert status(0)='1' and status(1)='0' and cid=x"123456789ABCDEF0" severity failure;
    assert unsigned(status(63 downto 48))=4 report "N=10 ownership is not balanced 4/3/3" severity failure;
    for i in 8 to 15 loop
      reject_reserved(i,x"0000000000000001",x"0000000000000000");
      write_word(i,x"0000000000000000");assert status(1)='0' report "Normalized zero reserved word was rejected" severity failure;
    end loop;
    for i in 0 to 3 loop
      reject_reserved(19+4*i,x"8000000000000000",x"0000000000000000");
      write_word(19+4*i,x"0000000000000000");assert status(1)='0' severity failure;
    end loop;
    reject_reserved(0,x"000000000001000A",x"000000000000000A");
    reject_reserved(1,x"0000000A0100186A",x"0000000A0000186A");
    reject_reserved(3,x"0000000000000440",x"0000000000000040");
    reject_reserved(3,x"0000000001000040",x"0000000000000040");
    reject_reserved(3,x"0001000000000040",x"0000000000000040");
    reject_reserved(16,x"0000000300000000",x"0000000100000000");
    reject_reserved(18,x"0000000000011001",x"0000000000010001");
    reject_reserved(18,x"0000000010010001",x"0000000000010001");
    -- Allowed endpoint values and fractional/significant high bits survive
    -- shadow staging and commit without losing timing precision.
    write_word(1,x"0000FFFF00FFFFFF");write_word(2,x"FEDCBA9876543210");
    write_word(3,x"0000FFFF00FF0271");write_word(16,x"0000000100418937");
    write_word(17,x"FFFFFFFFFFFFFFF1");write_word(18,x"000000000FFF0FFF");apply_cfg;
    assert status(1)='0' severity failure;
    read_word(16385,x"0000FFFF00FFFFFF");read_word(16386,x"FEDCBA9876543210");
    read_word(16387,x"0000FFFF00FF0271");read_word(16400,x"0000000100418937");
    read_word(16401,x"FFFFFFFFFFFFFFF1");read_word(16402,x"000000000FFF0FFF");
    write_word(1,x"0000000A0000186A");write_word(2,x"00000007A1200000");
    write_word(3,x"0000000000000040");write_word(16,x"0000000100000000");
    write_word(17,x"0000000000000000");write_word(18,x"0000000000010001");apply_cfg;
    shadow<=to_unsigned(6,16);apply<='1';tick;apply<='0';for i in 0 to 5 loop tick;end loop;
    assert obs(16)='1' and unsigned(obs(15 downto 0))=6 and ref='0' severity failure;
    shadow<=to_unsigned(9,16);apply<='1';tick;apply<='0';tick;
    assert obs(17)='1' and unsigned(obs(15 downto 0))=6 severity failure;
    write_word(0,x"000000000000000D");apply_cfg;
    assert status(1)='1' and unsigned(status(47 downto 32))=10 report "Invalid population was committed" severity failure;
    raw_before:=x"00"&status(231 downto 176);
    write_word(0,x"0000000000000006");apply_cfg;
    assert status(1)='0' and unsigned(status(47 downto 32))=6 and obs(16)='0' severity failure;
    assert unsigned(x"00"&status(231 downto 176))>unsigned(raw_before) report "Emulation reset reset the raw counter" severity failure;
    snapshot<='1';tick;snapshot<='0';tick;addr<=to_unsigned(32771,16);tick;original:=rd;
    for i in 0 to 100 loop tick;end loop;
    assert status(7)='1' and rd=original report "Frozen page moved" severity failure;
    snapshot<='1';tick;snapshot<='0';tick;assert unsigned(status(127 downto 96))=1 severity failure;
    ack<='1';tick;ack<='0';tick;assert status(7)='0' severity failure;
    report "PASS runtime registers, reserved masks/rejection, full timing precision, invalid commits, ownership, observer, raw monotonicity, stable pages and lost samples" severity note;stop;
  end process;
end;
