source {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/scripts/physical_hw.tcl}
set physical_hw::targets {OBS001A OBS003A OBS002A}
set physical_hw::ltx {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/build/physical_runtime/obsidian_benchmark.ltx}
set bit {C:/Users/afarahhass/Documents/Xilinx_project/Obsidian_RAG/build/physical_runtime/obsidian_benchmark.bit}
open_hw_manager
connect_hw_server
# Preflight all three devices before modifying any FPGA.
foreach serial $physical_hw::targets {
 set ts [get_hw_targets */$serial]
 if {[llength $ts]!=1} {error "Missing/ambiguous cable $serial"}
 open_hw_target [lindex $ts 0]
 set ds [get_hw_devices -of_objects [current_hw_target]]
 if {[llength $ds]!=1 || [get_property PART [lindex $ds 0]] ne "xc7a35t"} {error "Unexpected FPGA on $serial"}
 close_hw_target
}
foreach serial $physical_hw::targets {
 open_hw_target [lindex [get_hw_targets */$serial] 0]
 set d [lindex [get_hw_devices -of_objects [current_hw_target]] 0]
 set_property PROGRAM.FILE $bit $d
 set_property PROBES.FILE $physical_hw::ltx $d
 puts "PROGRAM_BEGIN $serial";flush stdout
 program_hw_devices $d
 refresh_hw_device $d
 puts "PROGRAM_COMPLETE $serial";flush stdout
 close_hw_target
}
physical_hw::initialize
foreach serial $physical_hw::targets {puts "PROGRAMMED_IDLE $serial [format %064llx [physical_hw::status $serial]]"}
close_hw_manager
puts "PHYSICAL_PROGRAM_COMPLETE";flush stdout
