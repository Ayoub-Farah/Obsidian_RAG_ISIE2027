# Reproducible hardware diagnosis. Images must already be loaded.
# -tclargs ROOT OUTPUT; does not program FPGA or flash memory.
lassign $argv root output
file mkdir $output
source [file join $root scripts physical_hw.tcl]
set physical_hw::ltx [file normalize [file join $root build physical_runtime obsidian_benchmark.ltx]]
set physical_hw::targets {OBS001A OBS003A OBS002A}
set physical_hw::output [file join $output pages]
set physical_hw::timeout_ms 15000
file mkdir $physical_hw::output
proc stamp {message} {puts "[clock milliseconds] $message";flush stdout}
open_hw_manager
connect_hw_server
# Vivado invalidates probe objects when a cable is closed. Keep the current
# cable open until a different board is requested, then rediscover its probes.
rename close_hw_target native_close_hw_target
proc close_hw_target {args} {}
set connected_serial ""
proc physical_hw::select {serial} {
 if {$::connected_serial ne $serial} {
  if {$::connected_serial ne ""} {native_close_hw_target}
  set t [get_hw_targets */$serial]
  if {[llength $t]!=1} {error "Missing/ambiguous cable $serial"}
  open_hw_target [lindex $t 0]
  set d [lindex [get_hw_devices -of_objects [current_hw_target]] 0]
  if {[get_property PART $d] ne "xc7a35t"} {error "Unexpected device"}
  set_property PROBES.FILE $physical_hw::ltx $d
  stamp "REFRESH_DEVICE_BEGIN $serial"
  refresh_hw_device $d
  stamp "REFRESH_DEVICE_END $serial"
  set ::vio($serial) [lindex [get_hw_vios -of_objects $d] 0]
  set ::ila($serial) [lindex [get_hw_ilas -of_objects $d] 0]
  set ::connected_serial $serial
 }
 stamp "REFRESH_VIO_BEGIN $serial"
 refresh_hw_vio $::vio($serial)
 stamp "REFRESH_VIO_END $serial"
 return $::vio($serial)
}
rename physical_hw::read_word physical_hw::read_word_original
set read_count 0
proc physical_hw::read_word {v address} {
 incr ::read_count
 if {$::read_count%64==1} {stamp "READ_PROGRESS $::connected_serial words=$::read_count address=$address"}
 return [read_word_original $v $address]
}
proc snapshot {label} {
 foreach serial $::physical_hw::targets {
  set v [physical_hw::select $serial]
  foreach p [get_hw_probes -of_objects $v] {
   stamp "SNAPSHOT $label $serial PROBE=$p TYPE=[get_property TYPE $p] PORT=[get_property PROBE_PORT $p] VALUE=[obsidian_hw::read_probe $p]"
  }
  close_hw_target
 }
}
snapshot initial
# Hold reset everywhere before releasing any board, so no parser starts in
# the middle of a management frame from a board that has not yet been reset.
foreach serial $physical_hw::targets {obsidian_hw::write_output [physical_hw::select $serial] 0 1;close_hw_target}
foreach serial $physical_hw::targets {obsidian_hw::write_output [physical_hw::select $serial] 0 0;close_hw_target}
snapshot reset
foreach serial $physical_hw::targets {
 physical_hw::select $serial
 set i $ila($serial)
 set_property CONTROL.TRIGGER_POSITION 768 $i
 set p [get_hw_probes -of_objects $i -filter {PROBE_PORT == 0}]
 set_property TRIGGER_COMPARE_VALUE "eq256'b[string repeat x 243]1[string repeat x 12]" $p
 run_hw_ila $i
 stamp "ILA_ARMED $serial"
 close_hw_target
}
if {[catch {
 physical_hw::configure 0000186a00000004000100020101000700000001
 snapshot configured
 physical_hw::run 4 0
} problem options]} {stamp "TEST_FAILED $problem";puts [dict get $options -errorinfo]} else {stamp RUN_COLLECTED}
snapshot final
foreach serial $physical_hw::targets {
 physical_hw::select $serial
 set i $ila($serial)
 stamp "ILA_READ_BEGIN $serial"
 set data [upload_hw_ila_data $i]
 write_hw_ila_data -csv_file [file join $output ${serial}_ila.csv] $data
 stamp "ILA_SAVED $serial"
 close_hw_target
}
close_hw_manager
stamp DEBUG_COMPLETE
