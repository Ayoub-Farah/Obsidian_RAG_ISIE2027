# Rebuild source-only Obsidian benchmark. Vivado 2025.2 is required.
# vivado -mode batch -source scripts/create_project.tcl -tclargs MODE N BASE LOCAL D R RUN_CYCLES
if {![string match "2025.2*" [version -short]]} {error "Use Vivado 2025.2; got [version -short]"}
set root [file normalize [file join [file dirname [info script]] ..]]
set family benchmark
set default_mode 2
if {[file exists [file join $root family.tcl]]} {source [file join $root family.tcl]}
set values [list $default_mode 3 0 1 6 2 128]
if {[llength $argv] > 7} {error "Expected MODE N BASE LOCAL D R RUN_CYCLES"}
for {set i 0} {$i < [llength $argv]} {incr i} {lset values $i [lindex $argv $i]}
lassign $values mode nodes base local data_bytes ref_bytes run_cycles
foreach value $values {if {![string is integer -strict $value] || $value < 0} {error "Invalid nonnegative integer '$value'"}}
if {$nodes<2 || $local<1 || $base+$local>$nodes || $data_bytes<1 || $ref_bytes<1} {error "Invalid node mapping or payload sizes"}
if {$mode ni {0 1 2 3 4}} {error "Unsupported mode"}
if {$family eq "RAG" && $mode ni {0 2}} {error "RAG project supports modes 0 and 2"}
if {$family eq "CT" && $mode ni {1 3 4}} {error "CT project supports modes 1, 3 and 4"}
# Validate representability and actual aggregate per-frame slot capacity before
# creating a project or generating any proprietary IP output products.
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
set mode_name [lindex {RAG_C AGG_C RAG_D AGG_D2 AGG_D2_PIPE} $mode]
set validation_json [benchmark_exec_python $python [file join $root tools validate_profile.py] \
 --mode $mode_name --nodes $nodes --data-bytes $data_bytes --ref-bytes $ref_bytes \
 --node-base $base --local-nodes $local --fifo-words 2048]
puts $validation_json
set runtime 0
if {[info exists ::env(OBSIDIAN_RUNTIME_CONFIG)]} {set runtime $::env(OBSIDIAN_RUNTIME_CONFIG)}
if {$runtime ni {0 1}} {error "OBSIDIAN_RUNTIME_CONFIG must be 0 or 1"}
if {$runtime && ($nodes>30 || $nodes<3 || $mode ni {0 2})} {error "Runtime RAG supports capacity 3..30 only"}
set fifo_words 2048
set vlink_fifo 256
if {$runtime} {set fifo_words 128;set vlink_fifo 64}
set profile [string tolower "${family}_m${mode}_n${nodes}_b${base}_l${local}_d${data_bytes}_r${ref_bytes}_c${run_cycles}"]
if {$runtime} {append profile _runtime}
set build [file join $root build $profile]
file mkdir $build
set part xc7a35tcsg325-2
create_project -force $profile $build -part $part
set validation_file [open [file join $build profile_validation.json] w]
puts $validation_file $validation_json
close $validation_file
set_property target_language VHDL [current_project]
set_property simulator_language Mixed [current_project]
set_property default_lib xil_defaultlib [current_project]
set_property source_mgmt_mode All [current_project]

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

set vio_name benchmark_vio
set vio_outputs 4
if {$runtime} {set vio_name runtime_vio;set vio_outputs 5}
create_ip -name vio -vendor xilinx.com -library ip -module_name $vio_name
set_property -dict [list CONFIG.C_NUM_PROBE_IN 6 CONFIG.C_NUM_PROBE_OUT $vio_outputs \
 CONFIG.C_PROBE_IN0_WIDTH 256 CONFIG.C_PROBE_IN1_WIDTH 256 CONFIG.C_PROBE_IN2_WIDTH 256 CONFIG.C_PROBE_IN3_WIDTH 64 CONFIG.C_PROBE_IN4_WIDTH 2 CONFIG.C_PROBE_IN5_WIDTH 6 \
 CONFIG.C_PROBE_OUT0_WIDTH 1 CONFIG.C_PROBE_OUT1_WIDTH 1 CONFIG.C_PROBE_OUT2_WIDTH 1 CONFIG.C_PROBE_OUT3_WIDTH 8 \
 CONFIG.C_PROBE_OUT0_INIT_VAL 0 CONFIG.C_PROBE_OUT1_INIT_VAL 0 CONFIG.C_PROBE_OUT2_INIT_VAL 0 CONFIG.C_PROBE_OUT3_INIT_VAL 0] [get_ips $vio_name]
if {$runtime} {
 set initial_config [expr {2 | (3<<2) | (($base/$local)<<8) | (1<<14)}]
 set_property -dict [list CONFIG.C_PROBE_OUT4_WIDTH 32 CONFIG.C_PROBE_OUT4_INIT_VAL $initial_config] [get_ips $vio_name]
}
set ila_depth 1024
if {[info exists ::env(OBSIDIAN_ILA_DEPTH)]} {set ila_depth $::env(OBSIDIAN_ILA_DEPTH)}
if {$ila_depth ni {1024 2048 4096 8192 16384 32768 65536 131072}} {error "OBSIDIAN_ILA_DEPTH must be 1024,2048,4096,8192,16384,32768,65536,131072"}
create_ip -name ila -vendor xilinx.com -library ip -module_name benchmark_ila
set_property -dict [list CONFIG.C_NUM_OF_PROBES 3 CONFIG.C_DATA_DEPTH $ila_depth \
 CONFIG.C_PROBE0_WIDTH 256 CONFIG.C_PROBE1_WIDTH 64 CONFIG.C_PROBE2_WIDTH 96] [get_ips benchmark_ila]
generate_target all [get_ips [list $vio_name benchmark_ila]]
proc add_vhdl_tree {directory} {
 foreach f [glob -nocomplain -directory $directory *.vhd] {
  add_files -norecurse $f
  set_property FILE_TYPE {VHDL 2008} [get_files $f]
 }
 foreach d [glob -nocomplain -types d -directory $directory *] {add_vhdl_tree $d}
}
add_vhdl_tree [file join $root rtl]
add_files -norecurse $generated_adapter
set_property FILE_TYPE {VHDL 2008} [get_files $generated_adapter]
add_files -fileset constrs_1 -norecurse [file join $root constraints obsidian_benchmark.xdc]
set reset_cdc_xdc [file join $root constraints reset_cdc.xdc]
add_files -fileset constrs_1 -norecurse $reset_cdc_xdc
set_property USED_IN_SYNTHESIS false [get_files $reset_cdc_xdc]
set_property PROCESSING_ORDER LATE [get_files $reset_cdc_xdc]
set_property top obsidian_benchmark_top [current_fileset]
set_property generic "G_MODE=$mode G_NODES=$nodes G_NODE_BASE=$base G_LOCAL_NODES=$local G_DATA_BYTES=$data_bytes G_REF_BYTES=$ref_bytes G_RUN_CYCLES=$run_cycles G_RUNTIME_CONFIG=[expr {$runtime ? "true" : "false"}] G_FIFO_WORDS=$fifo_words G_VLINK_FIFO_WORDS=$vlink_fifo" [current_fileset]
update_compile_order -fileset sources_1
report_ip_status -file [file join $build ip_status.rpt]
set manifest [open [file join $build build_manifest.txt] w]
puts $manifest "runtime_config=$runtime\ncapacity=$nodes\nfifo_words=$fifo_words\nvlink_fifo_words=$vlink_fifo\nfamily=$family\nmode=$mode\nN=$nodes\nnode_base=$base\nlocal_nodes=$local\nD=$data_bytes\nR=$ref_bytes\nrun_cycles=$run_cycles\npart=$part\nVivado=[version -short]\nline_rate=1.25Gbps\nuser_clock=62.5MHz\nclock_compensation=enabled_IP_default\nstatus=project_generated_not_implemented"
close $manifest
puts "Project generated: [get_property DIRECTORY [current_project]]/$profile.xpr"
