# Helpers for already loaded physical_v3 images. No program_hw_devices call.
source [file join [file dirname [info script]] hw_helpers.tcl]
namespace eval physical_hw {variable targets;variable ltx;variable output;variable timeout_ms 300000}
proc physical_hw::select {serial} {
 variable ltx
 set ts [get_hw_targets */$serial]
 if {[llength $ts]!=1} {error "Expected one cable $serial, got $ts"}
 open_hw_target [lindex $ts 0]
 set ds [get_hw_devices -of_objects [current_hw_target]]
 if {[llength $ds]!=1 || [get_property PART [lindex $ds 0]] ne "xc7a35t"} {error "Unexpected FPGA: $ds"}
 set d [lindex $ds 0];set_property PROBES.FILE $ltx $d;refresh_hw_device $d
 set vs [get_hw_vios -of_objects $d]
 if {[llength $vs]!=1} {error "Expected one physical VIO"}
 set v [lindex $vs 0];refresh_hw_vio $v
 set s [expr 0x[obsidian_hw::read_input $v 0]]
 if {($s>>232)!=0x504803} {error "Wrong firmware VIO signature on $serial"}
 return $v
}
proc physical_hw::status {serial} {
 set v [select $serial];refresh_hw_vio $v
 set s [expr 0x[obsidian_hw::read_input $v 0]]
 close_hw_target
 if {$s & (1<<12)} {error "Firmware fault on $serial: [format %064llx $s]"}
 return $s
}
proc physical_hw::pulse {serial port} {
 set v [select $serial]
 obsidian_hw::write_output $v $port 0
 obsidian_hw::write_output $v $port 1
 obsidian_hw::write_output $v $port 0
 close_hw_target
}
proc physical_hw::wait_idle {} {
 variable targets;variable timeout_ms
 set end [expr {[clock milliseconds]+$timeout_ms}]
 while 1 {
  set s [status [lindex $targets 0]]
  if {($s & 255)==0 && !($s & (1<<11)) && !($s & (1<<18))} {return}
  if {[all_frozen]} {collect}
  if {[clock milliseconds]>$end} {error "Timeout waiting for coordinator idle"}
  after 10
 }
}
proc physical_hw::all_frozen {} {
 variable targets
 set all 1
 foreach serial $targets {if {!([status $serial] & (1<<18))} {set all 0}}
 return $all
}
proc physical_hw::wait_frozen {} {
 variable timeout_ms
 set end [expr {[clock milliseconds]+$timeout_ms}]
 while {![all_frozen]} {
  if {[clock milliseconds]>$end} {error "Timeout: global drain/page freeze not proved"}
  after 10
 }
}
proc physical_hw::read_word {v address} {
 obsidian_hw::write_output $v 3 [format %04x $address]
 refresh_hw_vio $v
 set value [string tolower [obsidian_hw::read_input $v 1]]
 if {![regexp {^[0-9a-f]{1,16}$} $value]} {error "Unknown journal data at $address: $value"}
 return [format %016llx [expr 0x$value]]
}
proc physical_hw::collect_board {serial board} {
 variable output
 set v [select $serial]
 set s [expr 0x[obsidian_hw::read_input $v 0]]
 if {!($s & (1<<18))} {error "Journal is not frozen"}
 set h0 [expr 0x[read_word $v 7168]];set h1 [expr 0x[read_word $v 7169]];set h2 [expr 0x[read_word $v 7170]]
 if {$h0!=0x5048595300030001 || (($h1>>48)&3)!=[string first $board ABC]} {error "Journal signature/role mismatch"}
 set ns [expr {($h1>>32)&65535}];set ne [expr {$h2&0xffffffff}];set nc [expr {$h2>>32}];set page [expr {$h1&0xffffffff}]
 if {$ns>128 || $ne>1024 || $nc>256} {error "Invalid page counts"}
 set addresses {}
 foreach {base size} [list 0 [expr {$ns*32}] 4096 [expr {$ne*2}] 6144 [expr {$nc*4}] 7168 16] {
  for {set j 0} {$j<$size} {incr j} {lappend addresses [expr {$base+$j}]}
 }
 set pass1 {};foreach address $addresses {lappend pass1 [read_word $v $address]}
 set pass2 {};foreach address $addresses {lappend pass2 [read_word $v $address]}
 if {$pass1 ne $pass2} {error "Frozen journal changed during double read"}
 refresh_hw_vio $v
 if {!([expr 0x[obsidian_hw::read_input $v 0]] & (1<<18))} {error "Journal unfroze during collection"}
 close_hw_target
 set words [lrepeat 8192 0000000000000000]
 foreach address $addresses value $pass1 {lset words $address $value}
 set path [file join $output [format "%s_page_%08d.json" $board $page]]
 if {[file exists $path]} {error "Refusing to overwrite $path"}
 set f [open $path w]
 puts $f "\{\"schema\":\"physical_v3\",\"source\":\"hardware_jtag\",\"board\":\"$board\",\"serial\":\"$serial\",\"unused_storage_zero_filled\":true,\"double_read_verified\":true,\"words\":\["
 puts $f "\"[join $words {","}]\""
 puts $f "\]\}";close $f
 puts "PAGE_COLLECTED $path summaries=$ns events=$ne calibration=$nc"
 return $s
}
proc physical_hw::collect {} {
 variable targets
 wait_frozen
 set statuses {};foreach serial $targets board {A B C} {lappend statuses [collect_board $serial $board]}
 # Followers clear first; A cannot re-arm while any follower page is frozen.
 foreach serial [list [lindex $targets 1] [lindex $targets 2] [lindex $targets 0]] {pulse $serial 7}
 return $statuses
}
proc physical_hw::configure {word} {
 variable targets;variable timeout_ms
 if {[llength [lsort -unique $targets]]!=3} {error "Three unique cables required"}
 # Stage all shadow words/roles before any configuration command.
 foreach serial $targets role {0 1 2} {
  set v [select $serial]
  obsidian_hw::write_output $v 4 $word
  obsidian_hw::write_output $v 5 [format %x $role]
  close_hw_target
 }
 foreach serial [list [lindex $targets 1] [lindex $targets 2] [lindex $targets 0]] {pulse $serial 6}
 set end [expr {[clock milliseconds]+$timeout_ms}]
 while 1 {
  if {[all_frozen]} {collect}
  set ok 1
  foreach serial $targets role {0 1 2} {
   set v [select $serial];refresh_hw_vio $v
   set s [expr 0x[obsidian_hw::read_input $v 0]]
   set active [expr 0x[obsidian_hw::read_input $v 2]]
   set links [expr 0x[obsidian_hw::read_input $v 4]]
   close_hw_target
   if {$s & (1<<12)} {error "Controller fault during configure"}
   if {$s & (1<<10)} {error "Configuration rejected by $serial"}
   if {$active!=[expr 0x$word] || !($s & (1<<8)) || (($s>>23)&3)!=$role || $links!=3} {set ok 0}
  }
  if {$ok} {puts "CONFIGURATION_COMMITTED $word";return}
  if {[clock milliseconds]>$end} {error "Configuration did not commit coherently"}
  after 10
 }
}
proc physical_hw::run {repetitions post_calibration_ms} {
 variable targets
 wait_idle;pulse [lindex $targets 0] 1
 while 1 {
  set statuses [collect];set s [lindex $statuses 0]
  set completed [expr {($s>>96)&0xffffffff}]
  if {($repetitions!=0 && $completed>=$repetitions) || !($s & (1<<13))} {break}
 }
 wait_idle
 if {$post_calibration_ms>0} {
  # Collect a separate idle calibration page to bracket the measured run.
  after $post_calibration_ms;pulse [lindex $targets 0] 2;collect;wait_idle
 }
 puts "PHYSICAL_RUN_COMPLETE completed=$completed"
}
