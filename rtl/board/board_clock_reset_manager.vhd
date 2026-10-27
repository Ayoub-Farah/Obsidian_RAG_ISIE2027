library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- Horloge de controle toujours presente et reset de demarrage associe.
-- Le reset est immediatement reafirme si le MMCM perd son verrouillage,
-- puis reste actif G_RESET_HOLD_CYCLES fronts apres le retour du lock.
entity board_clock_reset_manager is
  generic (
    G_RESET_HOLD_CYCLES : positive := 1024;
    -- Reserve aux simulations generiques sans bibliotheque UNISIM.
    -- La valeur de production doit rester false.
    G_BYPASS_MMCM       : boolean  := false
  );
  port (
    clk_20_i       : in  std_logic;
    ctrl_clk_50_o  : out std_logic;
    ctrl_reset_o   : out std_logic;
    mmcm_locked_o  : out std_logic
  );

  attribute X_INTERFACE_INFO      : string;
  attribute X_INTERFACE_PARAMETER : string;

  attribute X_INTERFACE_INFO of clk_20_i : signal is
    "xilinx.com:signal:clock:1.0 CLK_20 CLK";
  attribute X_INTERFACE_PARAMETER of clk_20_i : signal is
    "XIL_INTERFACENAME CLK_20, FREQ_HZ 20000000";

  attribute X_INTERFACE_INFO of ctrl_clk_50_o : signal is
    "xilinx.com:signal:clock:1.0 CTRL_CLK_50 CLK";
  attribute X_INTERFACE_PARAMETER of ctrl_clk_50_o : signal is
    "XIL_INTERFACENAME CTRL_CLK_50, ASSOCIATED_RESET ctrl_reset_o, FREQ_HZ 50000000";

  attribute X_INTERFACE_INFO of ctrl_reset_o : signal is
    "xilinx.com:signal:reset:1.0 CTRL_RESET RST";
  attribute X_INTERFACE_PARAMETER of ctrl_reset_o : signal is
    "XIL_INTERFACENAME CTRL_RESET, POLARITY ACTIVE_HIGH";

end entity board_clock_reset_manager;

architecture rtl of board_clock_reset_manager is
  function bits_for_count(n : positive) return positive is
    variable value : natural := n - 1;
    variable bits  : positive := 1;
  begin
    while value > 1 loop
      value := value / 2;
      bits  := bits + 1;
    end loop;
    return bits;
  end function;

  component clock_20_to_50 is
    port (
      clk20_i  : in  std_logic;
      clk50_o  : out std_logic;
      locked_o : out std_logic
    );
  end component;

  constant C_COUNT_WIDTH : positive := bits_for_count(G_RESET_HOLD_CYCLES);

  signal ctrl_clk_50_int : std_logic;
  signal mmcm_locked_int : std_logic;
  signal hold_count      : unsigned(C_COUNT_WIDTH - 1 downto 0) :=
    (others => '0');
  signal ctrl_reset_reg  : std_logic := '1';
begin
  g_mmcm : if not G_BYPASS_MMCM generate
    u_clock_20_to_50 : clock_20_to_50
      port map (
        clk20_i  => clk_20_i,
        clk50_o  => ctrl_clk_50_int,
        locked_o => mmcm_locked_int
      );
  end generate g_mmcm;

  g_simulation_bypass : if G_BYPASS_MMCM generate
    ctrl_clk_50_int <= clk_20_i;
    mmcm_locked_int <= '1';
  end generate g_simulation_bypass;

  process (ctrl_clk_50_int, mmcm_locked_int)
  begin
    if mmcm_locked_int = '0' then
      hold_count     <= (others => '0');
      ctrl_reset_reg <= '1';
    elsif rising_edge(ctrl_clk_50_int) then
      if ctrl_reset_reg = '1' then
        if hold_count = to_unsigned(G_RESET_HOLD_CYCLES - 1,
                                    hold_count'length) then
          ctrl_reset_reg <= '0';
        else
          hold_count <= hold_count + 1;
        end if;
      end if;
    end if;
  end process;

  ctrl_clk_50_o <= ctrl_clk_50_int;
  ctrl_reset_o  <= ctrl_reset_reg;
  mmcm_locked_o <= mmcm_locked_int;
end architecture rtl;

