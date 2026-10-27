source {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/scripts/physical_hw.tcl}
open_hw_manager
connect_hw_server
set physical_hw::targets {OBS001A OBS003A OBS002A}
set physical_hw::ltx {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/build/physical_runtime/obsidian_benchmark.ltx}
set physical_hw::timeout_ms 300000
file mkdir {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/programming/final_status/pages}
set physical_hw::output {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/captures/retest_20261027_154813/programming/final_status/pages}
set fault_found 0
foreach t $physical_hw::targets {
 set v [physical_hw::select $t]
 set s [expr 0x[obsidian_hw::read_input $v 0]]
 puts "PHYSICAL_STATUS $t [format %064llx $s]"
 puts "PHYSICAL_DIAG $t raw=[obsidian_hw::read_input $v 3] links=[obsidian_hw::read_input $v 4] aurora_errors=[obsidian_hw::read_input $v 5] lost=[obsidian_hw::read_input $v 7]"
 close_hw_target
 if {$s & (1<<12)} {set fault_found 1}
}
if {$fault_found} {error "Firmware fault; all board snapshots were printed above"}
close_hw_manager
puts "PHYSICAL_COMMAND_COMPLETE"
