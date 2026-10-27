source {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/scripts/physical_hw.tcl}
open_hw_manager
connect_hw_server
set physical_hw::targets {OBS001A OBS003A OBS002A}
set physical_hw::ltx {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/build/physical_runtime/obsidian_benchmark.ltx}
set physical_hw::timeout_ms 60000
file mkdir {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/runtime_sequence/configuration_000}
set physical_hw::output {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/runtime_sequence/configuration_000}
physical_hw::configure 0000186a0000001000010002010100070000000a
physical_hw::run 16 0
file mkdir {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/runtime_sequence/configuration_001}
set physical_hw::output {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/runtime_sequence/configuration_001}
physical_hw::configure 0000186a0000001000020004010100070000000b
physical_hw::run 16 0
file mkdir {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/runtime_sequence/configuration_002}
set physical_hw::output {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/runtime_sequence/configuration_002}
physical_hw::configure 0000186a0000001000010002100005550000000c
physical_hw::run 16 0
close_hw_manager
puts "PHYSICAL_COMMAND_COMPLETE"
