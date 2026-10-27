# Read and export an ILA acquisition. No FPGA programming and no QSPI writes.
# -tclargs /path/file.ltx OUTPUT_DIR EXACT_DEVICE_NAME [ACTION]
# ACTION = read (default), arm, start, stop, reset, trigger
source [file join [file dirname [info script]] hw_helpers.tcl]
if {[llength $argv]<3 || [llength $argv]>4} {error "Expected LTX OUTDIR EXACT_DEVICE_NAME ?ACTION?"}
lassign $argv ltx outdir name action
if {$action eq ""} {set action read}
if {$action ni {read arm start stop reset trigger}} {error "Unknown action $action"}
if {![file isfile $ltx]} {error "Missing LTX $ltx"}
file mkdir $outdir
open_hw_manager
connect_hw_server
set targets [get_hw_targets]
if {[info exists ::env(OBSIDIAN_HW_TARGET)]} {
 set targets [get_hw_targets $::env(OBSIDIAN_HW_TARGET)]
}
if {[llength $targets]!=1} {error "Select one cable with OBSIDIAN_HW_TARGET; candidates: $targets"}
open_hw_target [lindex $targets 0]
set ds [get_hw_devices -filter "NAME == $name"]
if {[llength $ds]!=1} {error "Select exactly one device, found $ds"}
set d [lindex $ds 0]
set_property PROBES.FILE [file normalize $ltx] $d
refresh_hw_device $d
set ilas [get_hw_ilas -of_objects $d]
set vios [get_hw_vios -of_objects $d]
if {[llength $ilas]!=1 || [llength $vios]!=1} {error "Expected one benchmark ILA and VIO"}
set ila [lindex $ilas 0]
set vio [lindex $vios 0]
proc set_control {vio index value} {obsidian_hw::write_output $vio $index $value}
# The RTL consumes a rising edge on start. Keep it high until stop/reset;
# passive read never drives a VIO output or restarts an already stopped run.
switch -- $action {
 arm {set_property CONTROL.TRIGGER_POSITION 64 $ila; run_hw_ila $ila; puts "ILA armed; run start on the ancre after all cards are ready."; return}
 start {set_control $vio 2 0; set_control $vio 1 1; puts "Start requested"; return}
 stop {set_control $vio 1 0; set_control $vio 2 1; puts "Drain/stop requested"; return}
 reset {set_control $vio 1 0; set_control $vio 2 0; set_control $vio 0 1; after 20; set_control $vio 0 0; return}
 trigger {run_hw_ila -trigger_now $ila; return}
}
refresh_hw_vio $vio
set vh [open [file join $outdir vio_snapshot.txt] w]
foreach p [get_hw_probes -of_objects $vio] {puts $vh "[get_property NAME $p] ([obsidian_hw::direction $p])=[obsidian_hw::read_probe $p]"}
close $vh
set data [upload_hw_ila_data $ila]
write_hw_ila_data -csv_file [file join $outdir ila.csv] $data
write_hw_ila_data -force [file join $outdir ila.ila] $data
puts "Captured $outdir/ila.csv; raw counters from different boards are not directly subtractable."
