# Verified mappings from Obsidian netlist and source branch constraints.
set_property PACKAGE_PIN D13 [get_ports clk20_vcxo_i]
set_property IOSTANDARD LVCMOS33 [get_ports clk20_vcxo_i]
create_clock -name clk20_vcxo -period 50.000 [get_ports clk20_vcxo_i]
set_property PACKAGE_PIN D6 [get_ports gt_refclk_p_i]
set_property PACKAGE_PIN D5 [get_ports gt_refclk_n_i]
create_clock -name gt_refclk_125 -period 8.000 [get_ports gt_refclk_p_i]
set_property PACKAGE_PIN H2 [get_ports sfp0_txp_o]
set_property PACKAGE_PIN H1 [get_ports sfp0_txn_o]
set_property PACKAGE_PIN E4 [get_ports sfp0_rxp_i]
set_property PACKAGE_PIN E3 [get_ports sfp0_rxn_i]
set_property PACKAGE_PIN F2 [get_ports sfp1_txp_o]
set_property PACKAGE_PIN F1 [get_ports sfp1_txn_o]
set_property PACKAGE_PIN A4 [get_ports sfp1_rxp_i]
set_property PACKAGE_PIN A3 [get_ports sfp1_rxn_i]
# GT channel/common placement and generated clocks are owned by generated IP XDC.
# Both Aurora cores share actual user/sync clock networks; no false async grouping.
# No fabricated debug GPIO: all instrumentation is carried over JTAG VIO/ILA.
set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]
set_property CONFIG_MODE SPIx1 [current_design]
set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 1 [current_design]
