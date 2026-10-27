# One runtime image for A/B/C. All mode/size/H/campaign settings are VIO registers.
if {![string match "2025.2*" [version -short]]} {error "Vivado 2025.2 required"}
set root [file normalize [file join [file dirname [info script]] ..]]
set build [file join $root build physical_runtime]
set part xc7a35tcsg325-2
file mkdir $build
set reuse 0
if {[info exists ::env(OBSIDIAN_REUSE_IP)] && $::env(OBSIDIAN_REUSE_IP) eq "1"} {set reuse 1}
if {$reuse} {open_project [file join $build physical_runtime.xpr]} else {create_project -force physical_runtime $build -part $part}
set_property target_language VHDL [current_project]
set_property simulator_language Mixed [current_project]
set_property default_lib xil_defaultlib [current_project]
set_property source_mgmt_mode All [current_project]
if {!$reuse} {
source [file join $root scripts aurora_common.tcl]

create_ip -name vio -vendor xilinx.com -library ip -module_name physical_vio
set_property -dict [list CONFIG.C_NUM_PROBE_IN 8 CONFIG.C_NUM_PROBE_OUT 8 \
 CONFIG.C_PROBE_IN0_WIDTH 256 CONFIG.C_PROBE_IN1_WIDTH 64 CONFIG.C_PROBE_IN2_WIDTH 160 \
 CONFIG.C_PROBE_IN3_WIDTH 64 CONFIG.C_PROBE_IN4_WIDTH 2 CONFIG.C_PROBE_IN5_WIDTH 6 \
 CONFIG.C_PROBE_IN6_WIDTH 64 CONFIG.C_PROBE_IN7_WIDTH 64 \
 CONFIG.C_PROBE_OUT0_WIDTH 1 CONFIG.C_PROBE_OUT1_WIDTH 1 CONFIG.C_PROBE_OUT2_WIDTH 1 \
 CONFIG.C_PROBE_OUT3_WIDTH 13 CONFIG.C_PROBE_OUT4_WIDTH 160 CONFIG.C_PROBE_OUT5_WIDTH 2 \
 CONFIG.C_PROBE_OUT6_WIDTH 1 CONFIG.C_PROBE_OUT7_WIDTH 1 \
 CONFIG.C_PROBE_OUT0_INIT_VAL 0 CONFIG.C_PROBE_OUT1_INIT_VAL 0 CONFIG.C_PROBE_OUT2_INIT_VAL 0 \
 CONFIG.C_PROBE_OUT3_INIT_VAL 0 CONFIG.C_PROBE_OUT4_INIT_VAL 0x0000186A00000080000100021000000600000001 \
 CONFIG.C_PROBE_OUT5_INIT_VAL 3 CONFIG.C_PROBE_OUT6_INIT_VAL 0 CONFIG.C_PROBE_OUT7_INIT_VAL 0] [get_ips physical_vio]
create_ip -name ila -vendor xilinx.com -library ip -module_name benchmark_ila
set_property -dict [list CONFIG.C_NUM_OF_PROBES 3 CONFIG.C_DATA_DEPTH 1024 \
 CONFIG.C_PROBE0_WIDTH 256 CONFIG.C_PROBE1_WIDTH 64 CONFIG.C_PROBE2_WIDTH 96] [get_ips benchmark_ila]
generate_target all [get_ips [list physical_vio benchmark_ila]]
} else {
 set generated_adapter [file join $build generated obsidian_dual_aurora.vhd]
 if {![file exists $generated_adapter] || [llength [get_ips physical_vio]]!=1} {error "Cannot reuse missing common-image IP"}
}
proc add_tree {directory} {
 foreach f [glob -nocomplain -directory $directory *.vhd] {
  add_files -norecurse $f;set_property FILE_TYPE {VHDL 2008} [get_files $f]
 }
 foreach d [glob -nocomplain -types d -directory $directory *] {add_tree $d}
}
add_tree [file join $root rtl]
add_files -norecurse $generated_adapter
set_property FILE_TYPE {VHDL 2008} [get_files $generated_adapter]
add_files -fileset constrs_1 -norecurse [file join $root constraints obsidian_benchmark.xdc]
set old_reset [get_files -quiet reset_cdc.xdc]
if {[llength $old_reset]>0} {remove_files $old_reset}
set reset_cdc_xdc [file join $root constraints physical_reset_cdc.xdc]
add_files -fileset constrs_1 -norecurse $reset_cdc_xdc
set_property USED_IN_SYNTHESIS false [get_files $reset_cdc_xdc]
set_property PROCESSING_ORDER LATE [get_files $reset_cdc_xdc]
set_property top obsidian_physical_top [current_fileset]
set_property generic {} [current_fileset]
update_compile_order -fileset sources_1
report_ip_status -file [file join $build ip_status.rpt]
set f [open [file join $build build_manifest.txt] w]
puts $f "schema=physical_v3\ncommon_image=1\nphysical_boards=3\nvirtual_nodes=0\nmax_payload=4096\nmax_local_bytes=1365\nmax_hops=65535\nrx_fifo_words=8192\njournal_words64=8192\nila_depth=1024\npart=$part\nVivado=[version -short]\nline_rate=1.25Gbps\nuser_clock=62.5MHz\nclock_compensation=enabled_IP_default\nstatus=project_generated_not_implemented"
close $f
