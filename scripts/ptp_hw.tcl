# Only operate an already loaded PTP image. No programming commands.
source [file join [file dirname [info script]] hw_helpers.tcl]
namespace eval ptp_hw {variable targets;variable ltx;variable timeout_ms 300000}
proc ptp_hw::select {serial} {
 variable ltx
 set ts [get_hw_targets */$serial]
 if {[llength $ts]!=1} {error "Expected one cable $serial"}
 open_hw_target [lindex $ts 0]
 set ds [get_hw_devices -of_objects [current_hw_target]]
 if {[llength $ds]!=1 || [get_property PART [lindex $ds 0]] ne "xc7a35t"} {error "Unexpected FPGA"}
 set d [lindex $ds 0];set_property PROBES.FILE $ltx $d;refresh_hw_device $d
 set vs [get_hw_vios -of_objects $d]
 if {[llength $vs]!=1} {error "Expected one PTP VIO"}
 # A new software VIO object can retain default OUTPUT_VALUE properties.
 # Read the hardware outputs into that cache before any whole-VIO commit;
 # -update_output_values reads signals and does not drive them (UG835).
 set v [lindex $vs 0];refresh_hw_vio -update_output_values $v
 if {([expr 0x[obsidian_hw::read_input $v 0]]>>232)!=0x505401} {error "Not a PTP_EMULATION v1 image"}
 return $v
}
proc ptp_hw::pulse_v {v port} {
 foreach value {0 1 0} {obsidian_hw::write_output $v $port $value}
}
proc ptp_hw::pulse {serial port} {set v [select $serial];pulse_v $v $port;close_hw_target}
proc ptp_hw::status {serial} {
 set v [select $serial];set s [expr 0x[obsidian_hw::read_input $v 0]];close_hw_target;return $s
}
proc ptp_hw::read_word {v address} {
 obsidian_hw::write_output $v 1 [format %04x $address]
 refresh_hw_vio $v
 return [format %016llx [expr 0x[obsidian_hw::read_input $v 1]]]
}
proc ptp_hw::stop_all {} {
 variable targets;variable timeout_ms
 foreach serial $targets {pulse $serial 6}
 set end [expr {[clock milliseconds]+$timeout_ms}]
 while 1 {
  set quiet 1
  foreach serial $targets {if {![expr {[status $serial] & 4}]} {set quiet 0}}
  if {$quiet} {return}
  if {[clock milliseconds]>$end} {error "PTP drain timeout; raw counters have not been reset"}
  after 10
 }
}
proc ptp_hw::wait_running {{allow_stopped_nominal 0}} {
 variable targets;variable timeout_ms
 set end [expr {[clock milliseconds]+$timeout_ms}]
 while 1 {
  set ready 1
  foreach serial $targets {
   set s [status $serial]
   if {$s&64} {error "PTP firmware fault on $serial"}
   set stopped_nominal [expr {$allow_stopped_nominal && ($s&1024) && !($s&2048) && ($s&4)}]
   if {($s&56)!=24 && !$stopped_nominal} {set ready 0}
  }
  if {$ready} {puts "PTP_ALL_LOCAL_NOMINAL_REACHED";return}
  if {[clock milliseconds]>$end} {error "PTP acquisition timeout; local status is not proof of global clock error"}
  after 10
 }
}
proc ptp_hw::check_active {expected nodes capacity} {
 variable targets
 foreach serial $targets role {0 1 2} {
  set v [select $serial];set s [expr 0x[obsidian_hw::read_input $v 0]]
  set cid [expr 0x[obsidian_hw::read_input $v 2]]
  set links [expr 0x[obsidian_hw::read_input $v 4]];close_hw_target
  if {!($s&1) || ($s&2) || (($s>>32)&65535)!=$nodes || (($s>>16)&65535)!=$capacity || (($s>>8)&3)!=$role || $cid!=[expr 0x$expected] || $links!=3} {
   error "Active config/hash/capacity/role/links mismatch on $serial"
  }
 }
}
proc ptp_hw::stage {serial role words capacity} {
 set v [select $serial];set s [expr 0x[obsidian_hw::read_input $v 0]]
 if {!(($s&4)) || (($s>>16)&65535)!=$capacity} {error "Board not idle or incorrect synthesized capacity"}
 obsidian_hw::write_output $v 7 [format %x $role]
 set address 0
 foreach value $words {
  obsidian_hw::write_output $v 1 [format %04x $address]
  obsidian_hw::write_output $v 2 $value;pulse_v $v 3
  if {[read_word $v $address] ne $value} {error "Shadow readback mismatch at $serial/$address"}
  incr address
 }
 close_hw_target
}
proc ptp_hw::observe {serial node} {
 variable timeout_ms
 set v [select $serial]
 obsidian_hw::write_output $v 8 [format %04x $node]
 obsidian_hw::write_output $v 10 1;pulse_v $v 9
 set end [expr {[clock milliseconds]+$timeout_ms}]
 while 1 {
  refresh_hw_vio $v;set s [expr 0x[obsidian_hw::read_input $v 3]]
  if {$s & (1<<17)} {error "Observation selection rejected; previous selection retained"}
  if {($s & 65535)==$node && ($s & (1<<16))} {break}
  if {[clock milliseconds]>$end} {error "Observation transition timeout"}
  after 1
 }
 puts "PTP_OBSERVATION_ACTIVE $serial node_id=$node module=M[expr {$node+1}] valid=1"
 close_hw_target
}
proc ptp_hw::collect {serial filename} {
 set v [select $serial];set s [expr 0x[obsidian_hw::read_input $v 0]]
 if {!($s&128)} {pulse_v $v 11;refresh_hw_vio $v;set s [expr 0x[obsidian_hw::read_input $v 0]]}
 if {!($s&128)} {error "Snapshot page did not freeze"}
 set nodes [expr {($s>>32)&65535}];set first [expr {($s>>48)&65535}]
 set count [expr {$nodes/3+((($s>>8)&3)<($nodes%3))}]
 set ne [expr {($s>>160)&65535}]
 set addresses {}
 for {set i 0} {$i<8+16*$count} {incr i} {lappend addresses [expr {32768+$i}]}
 for {set i 0} {$i<4*$ne} {incr i} {lappend addresses [expr {36864+$i}]}
 foreach pass {1 2} {
  set words {}
  foreach addr $addresses {lappend words [read_word $v $addr]}
  set pass$pass $words
 }
 if {$pass1 ne $pass2} {error "Frozen snapshot changed during double read"}
 refresh_hw_vio $v;set after [expr 0x[obsidian_hw::read_input $v 0]]
 if {!($after&128) || (($after>>64)&0xffffffff)!=(($s>>64)&0xffffffff)} {error "Snapshot page identity changed during read"}
 if {[file exists $filename]} {error "Refusing to overwrite page"}
 set f [open $filename w]
 puts $f "\{\"schema\":\"ptp_emulation_page_v1\",\"source\":\"hardware_jtag\",\"status\":\"[format %064llx $s]\",\"double_read_verified\":true,\"snapshot_words\":\[\"[join [lrange $pass1 0 [expr {7+16*$count}]] {","}]\"\],\"event_words\":\["
 if {$ne>0} {puts $f "\"[join [lrange $pass1 [expr {8+16*$count}] end] {","}]\""}
 puts $f "\]\}";close $f
 pulse_v $v 12;close_hw_target
 puts "PTP_PAGE_COLLECTED $filename"
}
