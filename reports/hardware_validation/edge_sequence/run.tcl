source {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/scripts/physical_hw.tcl}
open_hw_manager
connect_hw_server
set physical_hw::targets {OBS001A OBS003A OBS002A}
set physical_hw::ltx {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/build/physical_runtime/obsidian_benchmark.ltx}
set physical_hw::timeout_ms 60000
file mkdir {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/edge_sequence/configuration_000}
set physical_hw::output {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/edge_sequence/configuration_000}
physical_hw::configure 000000400000000200010002000300010000001a
physical_hw::run 2 0
file mkdir {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/edge_sequence/configuration_001}
set physical_hw::output {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/edge_sequence/configuration_001}
physical_hw::configure 0000186a00000002000200010001000100000014
physical_hw::run 2 0
file mkdir {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/edge_sequence/configuration_002}
set physical_hw::output {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/edge_sequence/configuration_002}
physical_hw::configure 0000186a0000000200020002003f000700000015
physical_hw::run 2 0
file mkdir {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/edge_sequence/configuration_003}
set physical_hw::output {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/edge_sequence/configuration_003}
physical_hw::configure 0000186a00000002000200030101000700000016
physical_hw::run 2 0
file mkdir {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/edge_sequence/configuration_004}
set physical_hw::output {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/edge_sequence/configuration_004}
physical_hw::configure 0000186a00000002000200041000055500000017
physical_hw::run 2 0
file mkdir {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/edge_sequence/configuration_005}
set physical_hw::output {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/edge_sequence/configuration_005}
physical_hw::configure 00000040000000020002001d0001000100000018
physical_hw::run 2 0
file mkdir {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/edge_sequence/configuration_006}
set physical_hw::output {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/edge_sequence/configuration_006}
physical_hw::configure 0000186a000000010002ffff0001000100000019
physical_hw::run 1 0
file mkdir {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/edge_sequence/configuration_007}
set physical_hw::output {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/edge_sequence/configuration_007}
physical_hw::configure 0009896800000002000100020fff05550000001b
physical_hw::run 2 0
close_hw_manager
puts "PHYSICAL_COMMAND_COMPLETE"
