source {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/scripts/physical_hw.tcl}
open_hw_manager
connect_hw_server
set physical_hw::targets {OBS001A OBS003A OBS002A}
set physical_hw::ltx {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/build/physical_runtime/obsidian_benchmark.ltx}
set physical_hw::timeout_ms 60000
file mkdir {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/paged_sequence/pages}
set physical_hw::output {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/paged_sequence/pages}
physical_hw::configure 0000186a00000081000100020101000700000064
physical_hw::run 129 0
close_hw_manager
puts "PHYSICAL_COMMAND_COMPLETE"
