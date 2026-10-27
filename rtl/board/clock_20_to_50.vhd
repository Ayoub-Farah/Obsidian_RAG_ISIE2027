library ieee;
use ieee.std_logic_1164.all;

library unisim;
use unisim.vcomponents.all;

entity clock_20_to_50 is
  port (
    clk20_i  : in  std_logic;
    clk50_o  : out std_logic;
    locked_o : out std_logic
  );
end entity clock_20_to_50;

architecture rtl of clock_20_to_50 is
  signal clkfb     : std_logic;
  signal clkfb_buf : std_logic;
  signal clk50     : std_logic;
begin
  u_mmcm : MMCME2_BASE
    generic map (
      BANDWIDTH          => "OPTIMIZED",
      CLKIN1_PERIOD      => 50.000,
      CLKFBOUT_MULT_F    => 50.000,
      CLKFBOUT_PHASE     => 0.000,
      DIVCLK_DIVIDE      => 1,
      CLKOUT0_DIVIDE_F   => 20.000,
      CLKOUT0_DUTY_CYCLE => 0.500,
      CLKOUT0_PHASE      => 0.000,
      STARTUP_WAIT       => false
    )
    port map (
      CLKIN1   => clk20_i,
      CLKFBIN  => clkfb_buf,
      CLKFBOUT => clkfb,
      CLKOUT0  => clk50,
      CLKOUT0B => open,
      CLKOUT1  => open,
      CLKOUT1B => open,
      CLKOUT2  => open,
      CLKOUT2B => open,
      CLKOUT3  => open,
      CLKOUT3B => open,
      CLKOUT4  => open,
      CLKOUT5  => open,
      CLKOUT6  => open,
      LOCKED   => locked_o,
      PWRDWN   => '0',
      RST      => '0'
    );

  u_fb_buf : BUFG
    port map (
      I => clkfb,
      O => clkfb_buf
    );

  u_clk50_buf : BUFG
    port map (
      I => clk50,
      O => clk50_o
    );
end architecture rtl;
