# Freeze/drain, read journal, save raw records. No programming or reset.
# -tclargs LTX OUTPUT_JSON EXACT_DEVICE_NAME BOARD_ID
source [file join [file dirname [info script]] hw_helpers.tcl]
if {[llength $argv]!=4} {error "Expected LTX OUTPUT_JSON EXACT_DEVICE_NAME BOARD_ID"}
lassign $argv ltx outfile device board
if {![file isfile $ltx]} {error "Missing LTX $ltx"}
open_hw_manager
connect_hw_server
set targets [get_hw_targets]
if {[info exists ::env(OBSIDIAN_HW_TARGET)]} {
 set targets [get_hw_targets $::env(OBSIDIAN_HW_TARGET)]
}
if {[llength $targets]!=1} {error "Select one cable with OBSIDIAN_HW_TARGET; candidates: $targets"}
open_hw_target [lindex $targets 0]
set ds [get_hw_devices -filter "NAME == $device"]
if {[llength $ds]!=1} {error "Select exactly one device: $ds"}
set d [lindex $ds 0]
set_property PROBES.FILE [file normalize $ltx] $d
refresh_hw_device $d
set vs [get_hw_vios -of_objects $d]
if {[llength $vs]!=1} {error "Expected one benchmark VIO"}
set v [lindex $vs 0]
# Resolve probe objects once: scanning all properties per journal word makes
# hardware collection unnecessarily slow. A new board replaces this cache.
foreach index {0 1 2 3} {
 set ::obsidian_dump_in($index) [obsidian_hw::vio_probe $v in $index]
 set ::obsidian_dump_out($index) [obsidian_hw::vio_probe $v out $index]
}
proc value {v index} {return [get_property INPUT_VALUE $::obsidian_dump_in($index)]}
# Normalise the two 256-bit halves even if a tool omits leading zeroes.
proc hex256 {value} {
 set value [string map {_ ""} [string trim $value]]
 regsub -nocase {^0x} $value {} value
 if {![regexp {^[0-9a-fA-FxXzZ]+$} $value] || [string length $value]>64} {
  error "Expected at most 64 hexadecimal digits for a journal half"
 }
 return "[string repeat 0 [expr {64-[string length $value]}]][string tolower $value]"
}

proc hex_value {v index digits} {
 set h [string trim [value $v $index]]
 regsub -nocase {^0x} $h {} h
 if {![regexp {^[0-9a-fA-FxXzZ]+$} $h] || [string length $h]>$digits} {error "Invalid hex value from probe $index: $h"}
 return "[string repeat 0 [expr {$digits-[string length $h]}]][string tolower $h]"
}
proc output {v index value} {
 set_property OUTPUT_VALUE $value $::obsidian_dump_out($index)
 commit_hw_vio $v
}
proc escape_json {s} {return [string map [list \\ \\\\ \" \\\" \n \\n \r \\r] $s]}
# Halt new cycles, permit network drain, preserve the measurement raw counter.
output $v 1 0
output $v 2 1
after 100
refresh_hw_vio $v
set status_before [value $v 0]
# Require journal stability; two sweeps with equal records also catch a late
# drain completion and avoid claiming a torn or changing snapshot.
set first {}
set second {}
foreach pass {first second} {
 set data {}
 for {set address 0} {$address<256} {incr address} {
  output $v 3 [format %02x $address]
  refresh_hw_vio $v
  lappend data "[hex_value $v 2 64][hex_value $v 1 64]"
 }
 set $pass $data
}
if {$first ne $second} {error "Journal changed while reading; wait for drain and retry"}
refresh_hw_vio $v
set status_after [value $v 0]
set f [open $outfile w]
puts $f "\{\"board_id\":\"[escape_json $board]\",\"device\":\"[escape_json $device]\",\"vivado\":\"[version -short]\",\"raw_records_hex\":\["
for {set i 0} {$i<256} {incr i} {
 set comma [expr {$i<255 ? "," : ""}]
 puts $f "\"[lindex $second $i]\"$comma"
}
puts $f "\],\"status_hex\":\"$status_after\",\"raw_counter_hex\":\"[value $v 3]\",\"source\":\"hardware_jtag\"\}"
close $f
puts "Saved stable raw journal to $outfile. Decode with measurement schema; per-board raw clocks have distinct origins."
