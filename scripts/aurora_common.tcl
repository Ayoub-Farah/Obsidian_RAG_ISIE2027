# Verified Aurora configuration and generated-port contract, retained from original flow.
proc benchmark_exec_python {command args} {
 set saved_env [dict create]
 foreach key {PYTHONHOME PYTHONPATH} {
  if {[info exists ::env($key)]} {dict set saved_env $key $::env($key); unset ::env($key)}
 }
 set code [catch {exec {*}$command {*}$args} result]
 dict for {key value} $saved_env {set ::env($key) $value}
 if {$code} {error $result}
 return $result
}
set python {}
foreach candidate {{python3} {python} {py -3}} {
 if {[auto_execok [lindex $candidate 0]] ne "" &&
     ![catch {benchmark_exec_python $candidate -c {import sys; assert sys.version_info.major == 3}}]} {
  set python $candidate; break
 }
}
if {[llength $python]==0} {error "Python 3 required for static profile validation and IP contract checks"}
# Source branch config: 1 lane, 2-byte path, 1.25 Gbit/s, 125 MHz ref,
# 50 MHz init, framed duplex, no native flow control, application CRC.
# A single common PLL and clock infrastructure is owned by left/SFP0.
foreach {name lane support} {aurora_left 1 1 aurora_right 1 0} {
 create_ip -name aurora_8b10b -vendor xilinx.com -library ip -version 11.1 -module_name $name
 set_property CONFIG.SupportLevel 1 [get_ips $name]
 set_property -dict [list \
  CONFIG.C_AURORA_LANES 1 CONFIG.C_LANE_WIDTH 2 \
  CONFIG.C_LINE_RATE 1.25 CONFIG.C_REFCLK_FREQUENCY 125.000 \
  CONFIG.C_INIT_CLK 50.0 CONFIG.DRP_FREQ 50.0000 \
  CONFIG.Dataflow_Config Duplex CONFIG.Interface_Mode Framing CONFIG.Flow_Mode None \
  CONFIG.C_GT_LOC_1 $lane CONFIG.C_GT_CLOCK_1 GTPQ0 \
  CONFIG.C_START_QUAD X0Y0 CONFIG.C_START_LANE X0Y[expr {$lane-1}] \
  CONFIG.SINGLEEND_INITCLK [expr {$support == 1 ? "true" : "false"}] CONFIG.SINGLEEND_GTREFCLK false \
  CONFIG.C_USE_CRC false CONFIG.C_USE_SCRAMBLER false \
  CONFIG.TransceiverControl true] [get_ips $name]
 # Configure shared-resource mode after the common settings are validated.
 set_property CONFIG.SupportLevel $support [get_ips $name]
 generate_target instantiation_template [get_ips $name]
 generate_target all [get_ips $name]
}

# Parse generated declarations instead of assuming that a different SupportLevel
# has the same ports. Unknown input ports are a hard build error.
proc find_file {directory pattern} {
 set found [glob -nocomplain -directory $directory $pattern]
 if {[llength $found]>0} {return [lindex $found 0]}
 foreach d [glob -nocomplain -types d -directory $directory *] {
  set f [find_file $d $pattern]
  if {$f ne ""} {return $f}
 }
 return ""
}
set left_vho [find_file $build aurora_left.vho]
set right_vho [find_file $build aurora_right.vho]
if {$left_vho eq "" || $right_vho eq ""} {error "Missing generated Aurora instantiation templates"}
set generated_adapter [file join $build generated obsidian_dual_aurora.vhd]
set result [benchmark_exec_python $python [file join $root scripts generate_aurora_adapter.py] $left_vho $right_vho $generated_adapter]
puts $result

