-- Cycle equivalence of observable outputs, including a second acquisition
-- after reset while the previous delay history remains in the RTL registers.
library ieee;use ieee.std_logic_1164.all;use ieee.numeric_std.all;use std.env.all;
use work.ptp_emulation_pkg.all;
entity tb_sync_median_enable is end;
architecture test of tb_sync_median_enable is
  type flags_t is array(0 to 2) of std_logic_vector(7 downto 0);
  type stats_t is array(0 to 2) of std_logic_vector(127 downto 0);
  signal clk:std_logic:='0';signal rst:std_logic:='1';signal start,ready:std_logic:='0';signal ticks:natural:=0;
  signal ld,rd,rld,rrd,lrx,rrx:words16_t(0 to 2);signal lk,rk,rlk,rrk,lrk,rrk_in:keeps_t(0 to 2);
  signal lv,rv,ll,rl,rlv,rrv,rll,rrl,lrv,rrv_in,lrl,rrl_in:std_logic_vector(0 to 2);
  signal times,rtimes,raw,rraw,offsets,roffsets,paths,rpaths,theta,rtheta,ages,rages:words64_t(0 to 2);
  signal f,rf:flags_t;signal stats,rstats:stats_t;signal al,ar,ral,rar:audits_t(0 to 2);
begin
  clk<=not clk after 8 ns;ready<='0' when ticks mod 7=0 else '1';
  process(clk)begin if rising_edge(clk)then ticks<=ticks+1;end if;end process;
  nodes:for i in 0 to 2 generate
  begin
    current:entity work.sync_system generic map(G_NODE_ID=>i,G_NODES=>3,G_PERIOD_CYCLES=>1000,G_ARM_DELAY_CYCLES=>5000,
      G_RUN_CYCLES=>0,G_EXTERNAL_SCHEDULER=>true,G_RUNTIME_TIMING=>true)
      port map(clk,rst,start,'0','1','1',lrx(i),lrk(i),lrv(i),lrl(i),rrx(i),rrk_in(i),rrv_in(i),rrl_in(i),
        ld(i),lk(i),lv(i),ll(i),ready,rd(i),rk(i),rv(i),rl(i),ready,f(i)(0),open,f(i)(1),f(i)(2),f(i)(3),
        raw(i),times(i),offsets(i),paths(i),stats(i)(31 downto 0),f(i)(4),
        external_raw_i=>raw(i),left_rx_raw_i=>raw(i),right_rx_raw_i=>raw(i),left_rx_time_i=>times(i),right_rx_time_i=>times(i),
        busy_o=>f(i)(5),holdover_o=>f(i)(6),audit_left_o=>al(i),audit_right_o=>ar(i),
        logical_step_i=>(unsigned'(x"0000000100000000")+to_unsigned(8589*i,64)),period_cycles_i=>1000,sync_interval_i=>2,
        theta_o=>theta(i),accepted_age_o=>ages(i),accepted_count_o=>stats(i)(63 downto 32),
        rejected_count_o=>stats(i)(95 downto 64),deferred_count_o=>stats(i)(127 downto 96),idle_o=>f(i)(7));
    reference:entity work.sync_system_median_reference generic map(G_NODE_ID=>i,G_NODES=>3,G_PERIOD_CYCLES=>1000,G_ARM_DELAY_CYCLES=>5000,
      G_RUN_CYCLES=>0,G_EXTERNAL_SCHEDULER=>true,G_RUNTIME_TIMING=>true)
      port map(clk,rst,start,'0','1','1',lrx(i),lrk(i),lrv(i),lrl(i),rrx(i),rrk_in(i),rrv_in(i),rrl_in(i),
        rld(i),rlk(i),rlv(i),rll(i),ready,rrd(i),rrk(i),rrv(i),rrl(i),ready,rf(i)(0),open,rf(i)(1),rf(i)(2),rf(i)(3),
        rraw(i),rtimes(i),roffsets(i),rpaths(i),rstats(i)(31 downto 0),rf(i)(4),
        external_raw_i=>raw(i),left_rx_raw_i=>raw(i),right_rx_raw_i=>raw(i),left_rx_time_i=>times(i),right_rx_time_i=>times(i),
        busy_o=>rf(i)(5),holdover_o=>rf(i)(6),audit_left_o=>ral(i),audit_right_o=>rar(i),
        logical_step_i=>(unsigned'(x"0000000100000000")+to_unsigned(8589*i,64)),period_cycles_i=>1000,sync_interval_i=>2,
        theta_o=>rtheta(i),accepted_age_o=>rages(i),accepted_count_o=>rstats(i)(63 downto 32),
        rejected_count_o=>rstats(i)(95 downto 64),deferred_count_o=>rstats(i)(127 downto 96),idle_o=>rf(i)(7));
    link_f:entity work.ptp_neighbor_link port map(clk,rst,7,to_unsigned(0,8),to_unsigned(1,32),to_unsigned(0,16),
      rd(i),rk(i),rv(i) and ready,rl(i),open,lrx((i+1) mod 3),lrk((i+1) mod 3),lrv((i+1) mod 3),lrl((i+1) mod 3),open,open);
    link_r:entity work.ptp_neighbor_link port map(clk,rst,5,to_unsigned(0,8),to_unsigned(2,32),to_unsigned(0,16),
      ld((i+1) mod 3),lk((i+1) mod 3),lv((i+1) mod 3) and ready,ll((i+1) mod 3),open,rrx(i),rrk_in(i),rrv_in(i),rrl_in(i),open,open);
  end generate;
  process begin wait for 132 ns;rst<='0';wait for 64 ns;start<='1';wait for 32 ns;start<='0';
    wait for 480 us;rst<='1';wait for 128 ns;rst<='0';wait for 64 ns;start<='1';wait for 32 ns;start<='0';wait;end process;
  process
  begin
    wait until falling_edge(clk);
    for i in 0 to 2 loop
      assert ld(i)=rld(i) and rd(i)=rrd(i) and lk(i)=rlk(i) and rk(i)=rrk(i) and lv(i)=rlv(i) and rv(i)=rrv(i) and ll(i)=rll(i) and rl(i)=rrl(i) report "Median enable changed a transmitted stream" severity failure;
      assert raw(i)=rraw(i) and times(i)=rtimes(i) and offsets(i)=roffsets(i) and paths(i)=rpaths(i) and f(i)=rf(i) and stats(i)=rstats(i) and theta(i)=rtheta(i) and ages(i)=rages(i) and al(i)=ral(i) and ar(i)=rar(i) report "Median enable changed observable state" severity failure;
    end loop;
    if ticks=60000 then assert f(2)(1)='1' and f(2)(2)='1' report "Equivalence fixture never acquired" severity failure;
      report "PASS cycle equivalence of median register enable: drift, asymmetry, stalls, acquisition, maintenance and reset/reacquisition" severity note;stop;end if;
  end process;
end;
