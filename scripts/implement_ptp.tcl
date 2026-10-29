# Reopen the exact validated synthesized netlist, including all embedded XDC.
# No IP generation, synthesis, or hardware-manager commands are run here.
if {![string match "2025.2*" [version -short]]} {error "Vivado 2025.2 required"}
foreach ptp_route_name {OBSIDIAN_PTP_ROOT OBSIDIAN_PTP_BUILD OBSIDIAN_PTP_ROUTE_SYNTH} {
 if {![info exists ::env($ptp_route_name)]} {error "Missing route input: $ptp_route_name"}
}
set ptp_route_root $::env(OBSIDIAN_PTP_ROOT)
set ptp_route_build $::env(OBSIDIAN_PTP_BUILD)
open_checkpoint $::env(OBSIDIAN_PTP_ROUTE_SYNTH)
if {[get_property PART [current_project]] ne "xc7a35tcsg325-2"} {error "Checkpoint part mismatch"}
# A reopened design's NAME may be the checkpoint basename. Verify the actual
# fingerprint-bound PTP netlist rather than that session/display name.
set ptp_route_cell [get_cells -quiet u_ptp]
if {[llength $ptp_route_cell]!=1 || [get_property REF_NAME $ptp_route_cell] ne "ptp_emulation_system"} {
 error "Checkpoint PTP hierarchy mismatch"
}
foreach ptp_route_expected_port {clk20_vcxo_i gt_refclk_p_i gt_refclk_n_i
 sfp0_txp_o sfp0_txn_o sfp1_txp_o sfp1_txn_o sfp0_rxp_i sfp0_rxn_i sfp1_rxp_i sfp1_rxn_i
 test_ref_m1_o test_obs_o} {
 if {[llength [get_ports -quiet $ptp_route_expected_port]]!=1} {error "Checkpoint board port missing: $ptp_route_expected_port"}
}
if {[info exists ::env(OBSIDIAN_PTP_IP_CACHE)]} {
 config_ip_cache -use_cache_location $::env(OBSIDIAN_PTP_IP_CACHE)
 set_property IP_CACHE_PERMISSIONS read [current_project]
 config_ip_cache -report -rptfile [file join $ptp_route_build ip_cache_before.rpt]
}

# Retain the exact physical-profile implementation and acceptance gates. Fail
# closed if that script changes its stage boundary or bitstream command.
set ptp_route_channel [open [file join $ptp_route_root scripts build.tcl] r]
set ptp_route_original [read $ptp_route_channel];close $ptp_route_channel
if {[regexp -all {(?m)^opt_design\r?$} $ptp_route_original]!=1 ||
    ![regexp -indices {(?m)^opt_design\r?$} $ptp_route_original ptp_route_start]} {error "Missing unique implementation stage"}
set ptp_route_implementation [string range $ptp_route_original [lindex $ptp_route_start 0] end]
set ptp_route_implementation [string map [list obsidian_benchmark obsidian_ptp {$build} {$ptp_route_build}] $ptp_route_implementation]
if {[regexp -all {write_bitstream -force} $ptp_route_implementation]!=1} {error "Missing unique bitstream acceptance boundary"}
if {[regexp {(?m)^\s*(synth_design|generate_target|create_project|launch_runs|open_hw_manager|program_hw_devices)\s} $ptp_route_implementation]} {
 error "Unexpected synthesis or hardware command in implementation stage"
}

set ptp_route_checks {
foreach ptp_route_port {test_ref_m1_o test_obs_o} {
 set ptp_route_paths [get_timing_paths -to [get_ports $ptp_route_port] -max_paths 1]
 if {[llength $ptp_route_paths]!=1 || [get_property SLACK [lindex $ptp_route_paths 0]]<0} {error "GPIO timing failed: $ptp_route_port"}
 set ptp_route_report [file join $ptp_route_build gpio_${ptp_route_port}.rpt]
 report_timing -to [get_ports $ptp_route_port] -max_paths 1 -file $ptp_route_report
 set ptp_route_channel [open $ptp_route_report r];set ptp_route_text [read $ptp_route_channel];close $ptp_route_channel
 if {![regexp {Requirement:\s+8\.000ns\s+\(MaxDelay Path} $ptp_route_text]} {error "Missing 8 ns register-to-pad constraint: $ptp_route_port"}
}
# The original setup/hold gates precede this hook. Also require the routed
# pulse-width summary to contain no negative slack or failing endpoints.
set ptp_route_channel [open [file join $ptp_route_build timing_summary.rpt] r]
set ptp_route_text [read $ptp_route_channel];close $ptp_route_channel
set ptp_route_header 0;set ptp_route_pulse_checked 0
foreach ptp_route_line [split $ptp_route_text "\n"] {
 if {[regexp {WNS\(ns\).+WHS\(ns\).+WPWS\(ns\)} $ptp_route_line]} {set ptp_route_header 1;continue}
 if {$ptp_route_header} {
  set ptp_route_values [regexp -all -inline {\S+} $ptp_route_line]
  if {[llength $ptp_route_values]==12 && [string is double -strict [lindex $ptp_route_values 0]] &&
      [string is double -strict [lindex $ptp_route_values 8]]} {
   if {[lindex $ptp_route_values 8]<0 || [lindex $ptp_route_values 9]<0 || [lindex $ptp_route_values 10]!=0} {error "Pulse-width timing did not pass"}
   set ptp_route_pulse_checked 1;break
  }
 }
}
if {!$ptp_route_pulse_checked} {error "Missing pulse-width timing summary"}
report_pulse_width -all_violators -file [file join $ptp_route_build pulse_width.rpt]
}
set ptp_route_implementation [string map [list {write_bitstream -force} "$ptp_route_checks\nwrite_bitstream -force"] $ptp_route_implementation]
# Keep the inherited script's existing variables local as well. Vivado may
# evaluate debug/IP callbacks in the global scope while opt_design is running.
proc ptp_route_run_implementation {ptp_route_build ptp_route_body} {
 eval $ptp_route_body
}
ptp_route_run_implementation $ptp_route_build $ptp_route_implementation
if {[info exists ::env(OBSIDIAN_PTP_IP_CACHE)]} {
 config_ip_cache -report -rptfile [file join $ptp_route_build ip_cache_after.rpt]
}
puts "ROUTE_FROM_SYNTH_COMPLETE $ptp_route_build"
