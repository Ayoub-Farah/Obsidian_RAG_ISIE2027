#!/usr/bin/env python3
"""Generate checked dual-duplex wrapper from the *actual* Vivado VHO files.
The master owns the single GTPE2_COMMON and clock buffers; the second core
uses that common PLL, USER_CLK and SYNC_CLK. Unknown vendor input => stop.
"""
from pathlib import Path
import argparse, re

def ports(path, module):
    text = path.read_text()
    m = re.search(r'(?:component|entity)\s+'+re.escape(module)+r'\s+(?:is\s+)?(?:.*?\bport\s*\()(.*?)(?:end\s+(?:component|entity))', text, re.S|re.I)
    if not m:
        raise ValueError(f'Cannot find complete VHDL declaration {module}: {path}')
    p = re.findall(r'(\w+)\s*:\s*(inout|in|out)\s+(std_logic(?:_vector\s*\([^)]*\))?)', m.group(1), re.I)
    if not p: raise ValueError('Empty IP interface')
    return [(n.lower(), d.lower(), t.lower()) for n,d,t in p]

def build(left, right):
    declarations=[]; instances=[]; signal_lines=[]; assignments=[]
    for idx,(module, pp) in enumerate((('aurora_left',left),('aurora_right',right))):
        declarations.append('component '+module+' is port (\n'+ ';\n'.join(f'  {n}: {d} {t}' for n,d,t in pp)+'\n); end component;')
        prefix='l' if idx==0 else 'r'
        mapping=[]
        needed={'s_axi_tx_tdata','s_axi_tx_tkeep','s_axi_tx_tlast','s_axi_tx_tvalid','s_axi_tx_tready','m_axi_rx_tdata','m_axi_rx_tkeep','m_axi_rx_tlast','m_axi_rx_tvalid','txp','txn','rxp','rxn','channel_up','reset','gt_reset','init_clk_in'}
        found={n for n,_,_ in pp}
        if needed-found: raise ValueError(f'{module}: essential ports absent {sorted(needed-found)}')
        if idx==0:
            for n in ['user_clk_out','sync_clk_out','gt_refclk1_out','gt0_pll0outclk_out','gt0_pll1outclk_out','gt0_pll0outrefclk_out','gt0_pll1outrefclk_out','quad1_common_lock_out']:
                if n not in found: raise ValueError('Master SupportLevel must be 1; absent '+n)
        else:
            for n in ['user_clk','sync_clk','gt_refclk1','gt0_pll0outclk_in','gt0_pll1outclk_in','quad1_common_lock_in']:
                if n not in found: raise ValueError('Slave SupportLevel must be 0; absent '+n)
        share={'user_clk_out':'user_clk','user_clk':'user_clk','sync_clk_out':'sync_clk','sync_clk':'sync_clk',
               'gt_refclk1_out':'refclk','gt_refclk1':'refclk','pll_not_locked_out':'pll_not_locked','pll_not_locked':'pll_not_locked',
               'gt0_pll0refclklost_out':'refclklost','gt0_pll0refclklost_in':'refclklost','quad1_common_lock_out':'common_lock','quad1_common_lock_in':'common_lock',
               'gt0_pll0outclk_out':'pll0clk','gt0_pll0outclk_in':'pll0clk','gt0_pll1outclk_out':'pll1clk','gt0_pll1outclk_in':'pll1clk',
               'gt0_pll0outrefclk_out':'pll0ref','gt0_pll0outrefclk_in':'pll0ref','gt0_pll1outrefclk_out':'pll1ref','gt0_pll1outrefclk_in':'pll1ref',
               'gt0_pll0lock_out':'pll0lock','gt0_pll0lock_in':'pll0lock','gt0_pll1lock_out':'pll1lock','gt0_pll1lock_in':'pll1lock'}
        common={'init_clk_in':'init_clk_i','drpclk_in':'init_clk_i','reset':'aurora_reset','gt_reset':'gt_reset',
                'gt_refclk1_p':'gt_refclk_p_i','gt_refclk1_n':'gt_refclk_n_i',
                'channel_up':f'channel_up_o({idx})','hard_err':f'hard_err_o({idx})','soft_err':f'soft_err_o({idx})','frame_err':f'frame_err_o({idx})'}
        for n,d,t in pp:
            if n in share:
                # Only master exports shared resources; slave may export diagnostics.
                expr=share[n] if idx==0 or d=='in' else 'open'
            elif n in common: expr=common[n]
            elif n in {'txp','txn','rxp','rxn'}:
                sig=f'{prefix}_{n}'; signal_lines.append(f'signal {sig}: {t};')
                scalar=f'{prefix}_{n}_'+('i' if d=='in' else 'o')
                assignments.append(f'{sig}(0) <= {scalar};' if d=='in' else f'{scalar} <= {sig}(0);')
                expr=sig
            elif n.startswith('s_axi_tx_') or n.startswith('m_axi_rx_'):
                tail=n.split('_',3)[-1]  # tdata etc
                rx=n.startswith('m_axi_rx_')
                base=f'{prefix}_'+('rx_' if rx else 'tx_')+tail[1:]+('_o' if d=='out' else '_i')
                if 'vector' in t:
                    sig=f'{prefix}_{n}'; signal_lines.append(f'signal {sig}: {t};')
                    assignments.append(f'{base} <= {sig};' if d=='out' else f'{sig} <= {base};')
                    expr=sig
                else: expr=base
            elif d=='out': expr='open'
            elif n in {'loopback','drpaddr_in','drpen_in','drpdi_in','drpwe_in','power_down'} or re.fullmatch(r'gt0_(?:tx|rx|eye)\w*_in',n):
                if n=='gt0_txdiffctrl_in': expr='"1000"'
                elif 'vector' in t: expr="(others => '0')"
                else: expr="'0'"
            else: raise ValueError(f'Unmapped input {module}.{n} ({t}); review AMD contract before build')
            mapping.append(f'  {n} => {expr}')
        instances.append(f'u_{prefix}: {module} port map (\n'+',\n'.join(mapping)+'\n);')
    entity='''library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity obsidian_dual_aurora is port (
 init_clk_i,rst_i,gt_refclk_p_i,gt_refclk_n_i: in std_logic;
 l_txp_o,l_txn_o,r_txp_o,r_txn_o: out std_logic;
 l_rxp_i,l_rxn_i,r_rxp_i,r_rxn_i: in std_logic;
 user_clk_o: out std_logic;
 channel_up_o,hard_err_o,soft_err_o,frame_err_o: out std_logic_vector(1 downto 0);
 l_tx_data_i,r_tx_data_i: in std_logic_vector(15 downto 0);
 l_tx_keep_i,r_tx_keep_i: in std_logic_vector(1 downto 0);
 l_tx_valid_i,r_tx_valid_i,l_tx_last_i,r_tx_last_i: in std_logic;
 l_tx_ready_o,r_tx_ready_o: out std_logic;
 l_rx_data_o,r_rx_data_o: out std_logic_vector(15 downto 0);
 l_rx_keep_o,r_rx_keep_o: out std_logic_vector(1 downto 0);
 l_rx_valid_o,r_rx_valid_o,l_rx_last_o,r_rx_last_o: out std_logic
); end entity;
architecture rtl of obsidian_dual_aurora is
'''
    body='''signal user_clk,sync_clk,refclk,pll_not_locked,refclklost,common_lock: std_logic;
signal pll0clk,pll1clk,pll0ref,pll1ref,pll0lock,pll1lock: std_logic;
signal gt_reset: std_logic := '1';
signal aurora_reset: std_logic := '1';
signal init_count: unsigned(6 downto 0) := (others=>'0');
signal release_user: std_logic := '0';
signal reset_pipe: std_logic_vector(2 downto 0) := (others=>'1');
attribute ASYNC_REG: string;
attribute ASYNC_REG of reset_pipe: signal is "TRUE";
begin
 user_clk_o <= user_clk;
 process(init_clk_i,rst_i) begin
  if rst_i='1' then init_count <= (others=>'0'); gt_reset<='1'; release_user<='0';
  elsif rising_edge(init_clk_i) then
   if init_count/=127 then init_count<=init_count+1; end if;
   if init_count>=31 then gt_reset<='0'; end if;
   if init_count>=47 then release_user<='1'; end if;
  end if;
 end process;
 process(user_clk,release_user) begin
  if release_user='0' then reset_pipe<=(others=>'1');
  elsif rising_edge(user_clk) then reset_pipe<=reset_pipe(1 downto 0)&'0'; end if;
 end process;
 process(user_clk) begin
  if rising_edge(user_clk) then aurora_reset<=reset_pipe(2); end if;
 end process;
'''
    return entity+'\n'.join(declarations+signal_lines)+'\n'+body+'\n'.join(assignments+instances)+'\nend architecture;\n'

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('left',type=Path); p.add_argument('right',type=Path); p.add_argument('output',type=Path); a=p.parse_args()
    result=build(ports(a.left,'aurora_left'),ports(a.right,'aurora_right'))
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(result)
    print(a.output)
