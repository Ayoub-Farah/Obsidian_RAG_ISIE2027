# Explicit programming command only. Never called by the build task.
# -tclargs /absolute/path/file.bit /absolute/path/file.ltx EXACT_DEVICE_NAME
if {[llength $argv]!=3} {error "Expected BIT LTX EXACT_DEVICE_NAME"}
lassign $argv bit ltx name
foreach f [list $bit $ltx] {if {![file isfile $f]} {error "Missing $f"}}
open_hw_manager
connect_hw_server
set targets [get_hw_targets]
if {[info exists ::env(OBSIDIAN_HW_TARGET)]} {
 set targets [get_hw_targets $::env(OBSIDIAN_HW_TARGET)]
}
if {[llength $targets]!=1} {error "Select one cable with OBSIDIAN_HW_TARGET; candidates: $targets"}
open_hw_target [lindex $targets 0]
set matches [get_hw_devices -filter "NAME == $name"]
if {[llength $matches]!=1} {error "Device selection must match exactly one: $matches"}
set d [lindex $matches 0]
set_property PROGRAM.FILE [file normalize $bit] $d
set_property PROBES.FILE [file normalize $ltx] $d
program_hw_devices $d
refresh_hw_device $d
