# PTP-only runtime image for A/B/C; one module per board by default.
if {![string match "2025.2*" [version -short]]} {error "Vivado 2025.2 required"}
set root [file normalize [file join [file dirname [info script]] ..]]
set capacity 1
if {[info exists ::env(OBSIDIAN_PTP_CAPACITY)]} {set capacity $::env(OBSIDIAN_PTP_CAPACITY)}
if {![string is integer -strict $capacity] || $capacity<1 || $capacity>20} {error "PTP capacity must be 1..20"}
set max_nodes [expr {min(60,3*$capacity)}]
set build $::env(OBSIDIAN_PTP_BUILD)
set part xc7a35tcsg325-2
file mkdir $build
set reuse 0
if {[info exists ::env(OBSIDIAN_REUSE_IP)] && $::env(OBSIDIAN_REUSE_IP) eq "1"} {set reuse 1}
if {$reuse} {open_project [file join $build ptp_emulation.xpr]} else {create_project -force ptp_emulation $build -part $part}
set_property target_language VHDL [current_project]
set_property simulator_language Mixed [current_project]
set_property default_lib xil_defaultlib [current_project]
set_property source_mgmt_mode All [current_project]
if {!$reuse} {
source [file join $root scripts aurora_common.tcl]

create_ip -name vio -vendor xilinx.com -library ip -module_name ptp_vio
set props [list CONFIG.C_NUM_PROBE_IN 6 CONFIG.C_NUM_PROBE_OUT 13 CONFIG.C_EN_PROBE_IN_ACTIVITY 0]
foreach i {0 1 2 3 4 5} width {256 64 64 64 2 6} {lappend props CONFIG.C_PROBE_IN${i}_WIDTH $width}
foreach i {0 1 2 3 4 5 6 7 8 9 10 11 12} width {1 16 64 1 1 1 1 2 16 1 1 1 1} {
 lappend props CONFIG.C_PROBE_OUT${i}_WIDTH $width CONFIG.C_PROBE_OUT${i}_INIT_VAL 0
}
# Invalid role until the stopped three-board configuration transaction.
lappend props CONFIG.C_PROBE_OUT7_INIT_VAL 3
set_property -dict $props [get_ips ptp_vio]
generate_target all [get_ips ptp_vio]
} else {
 set generated_adapter [file join $build generated obsidian_dual_aurora.vhd]
 if {![file exists $generated_adapter] || [llength [get_ips ptp_vio]]!=1} {error "Cannot reuse missing common-image IP"}
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
add_files -fileset constrs_1 -norecurse [file join $root constraints obsidian_ptp.xdc]
set old_reset [get_files -quiet reset_cdc.xdc]
if {[llength $old_reset]>0} {remove_files $old_reset}
set reset_cdc_xdc [file join $root constraints physical_reset_cdc.xdc]
add_files -fileset constrs_1 -norecurse $reset_cdc_xdc
set_property USED_IN_SYNTHESIS false [get_files $reset_cdc_xdc]
set_property PROCESSING_ORDER LATE [get_files $reset_cdc_xdc]
set_property top obsidian_ptp_top [current_fileset]
set_property generic [list G_CAPACITY=$capacity G_MAX_NODES=$max_nodes] [current_fileset]
update_compile_order -fileset sources_1
report_ip_status -file [file join $build ip_status.rpt]
set ptp_manifest_channel [open [file join $build build_manifest.txt] w]
puts $ptp_manifest_channel "schema=ptp_emulation_v1\ncommon_image=1\nphysical_boards=3\ncapacity=$capacity\nmax_nodes=$max_nodes\npart=$part\nVivado=[version -short]\nline_rate=1.25Gbps\nuser_clock=62.5MHz\nstatus=project_generated_not_implemented"
close $ptp_manifest_channel
