# Arm/read the common image's three ILAs; never programs or starts a run.
# -tclargs ROOT OUTPUT arm|read SERIAL_A SERIAL_B SERIAL_C
lassign $argv root output action a b c
if {$action ni {arm read} || [llength [lsort -unique [list $a $b $c]]]!=3} {error "Expected ROOT OUTPUT arm|read three distinct serials"}
file mkdir $output
source [file join $root scripts physical_hw.tcl]
set physical_hw::ltx [file normalize [file join $root build physical_runtime obsidian_benchmark.ltx]]
open_hw_manager
connect_hw_server
foreach serial [list $a $b $c] board {A B C} {
 set v [physical_hw::select $serial]
 set d [lindex [get_hw_devices -of_objects [current_hw_target]] 0]
 set ilas [get_hw_ilas -of_objects $d]
 if {[llength $ilas]!=1} {error "Expected one ILA on $serial"}
 set ila [lindex $ilas 0]
 if {$action eq "arm"} {
  set probes [get_hw_probes -of_objects $ila -filter {PROBE_PORT == 0}]
  if {[llength $probes]!=1} {error "Expected one 256-bit ILA status probe"}
  set_property CONTROL.TRIGGER_POSITION 64 $ila
  set_property TRIGGER_COMPARE_VALUE "eq256'b[string repeat x 244]1[string repeat x 11]" [lindex $probes 0]
  run_hw_ila $ila
  puts "ILA_ARMED $board $serial trigger=trial_live"
 } else {
  puts "ILA_READ_BEGIN $board $serial"
  set path [file join $output ${board}_ila.csv]
  if {[file exists $path]} {error "Refusing to overwrite $path"}
  set data [upload_hw_ila_data $ila]
  write_hw_ila_data -csv_file $path $data
  puts "ILA_SAVED $board $serial $path"
 }
 close_hw_target
 flush stdout
}
close_hw_manager
puts "PHYSICAL_ILA_COMPLETE"
