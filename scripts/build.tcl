# Same arguments as create_project.tcl. This command synthesizes and implements.
source [file join [file dirname [info script]] create_project.tcl]
# Compile in this Vivado process. Windows run launchers query WMI, which
# may be unavailable in restricted environments. Global IP synthesis uses
# the same generated sources without that external process launcher.
set_property generate_synth_checkpoint false [get_files -all *.xci]
generate_target all [get_ips]
synth_design -top obsidian_benchmark_top -part $part -generic [get_property generic [current_fileset]]
write_checkpoint -force [file join $build obsidian_benchmark_synth.dcp]
report_utilization -hierarchical -file [file join $build synthesis_utilization.rpt]
report_cdc -file [file join $build synthesis_cdc.rpt]
if {[info exists ::env(OBSIDIAN_SYNTH_ONLY)] && $::env(OBSIDIAN_SYNTH_ONLY) eq "1"} {
 puts "SYNTH_ONLY_COMPLETE $build";return
}
opt_design
place_design
phys_opt_design
route_design
write_checkpoint -force [file join $build obsidian_benchmark_routed.dcp]
# A dense profile can need one additional pass using actual routed delays.
# Keep every timing check below unchanged; this never accepts negative slack.
set routed_paths [get_timing_paths -no_report_unconstrained -max_paths 1]
if {[llength $routed_paths]>0 && [get_property SLACK [lindex $routed_paths 0]]<0} {
 puts "Refining routed timing with AggressiveExplore / Explore"
 phys_opt_design -directive AggressiveExplore
 route_design -directive Explore
 write_checkpoint -force [file join $build obsidian_benchmark_routed.dcp]
}
report_utilization -hierarchical -file [file join $build implementation_utilization.rpt]
report_timing_summary -report_unconstrained -file [file join $build timing_summary.rpt]
report_bus_skew -file [file join $build bus_skew.rpt]
set skew_file [open [file join $build bus_skew.rpt] r]
set skew_report [read $skew_file]
close $skew_file
if {[string first "VIOLATED" $skew_report]>=0} {error "Bus skew did not pass; inspect bus_skew.rpt"}
report_drc -file [file join $build drc.rpt]
report_cdc -file [file join $build cdc.rpt]
# A bitstream is deliverable only when timing and error-level DRC pass.
set paths [get_timing_paths -no_report_unconstrained -max_paths 1]
if {[llength $paths] == 0 || [get_property SLACK [lindex $paths 0]] < 0} {error "Timing did not pass; inspect timing_summary.rpt"}
set hold_paths [get_timing_paths -no_report_unconstrained -delay_type min -max_paths 1]
if {[llength $hold_paths]>0 && [get_property SLACK [lindex $hold_paths 0]] < 0} {error "Hold timing did not pass"}
set timing_checks [check_timing -override_defaults {no_clock unconstrained_internal_endpoints} -verbose -return_string]
set check_file [open [file join $build timing_checks.rpt] w]
puts $check_file $timing_checks
close $check_file
foreach check {no_clock unconstrained_internal_endpoints} {
 set pattern [format {checking %s \(([0-9]+)\)} $check]
 if {![regexp $pattern $timing_checks -> count] || $count != 0} {
  error "Unconstrained timing ($check); inspect timing_checks.rpt"
 }
}
set errors [get_drc_violations -filter {SEVERITY == Error}]
if {[llength $errors]>0} {error "DRC errors prevent bitstream: $errors"}
write_bitstream -force [file join $build obsidian_benchmark.bit]
write_debug_probes -force [file join $build obsidian_benchmark.ltx]
write_checkpoint -force [file join $build obsidian_benchmark_routed.dcp]
set manifest [open [file join $build build_manifest.txt] a]
puts $manifest "status=implemented_timing_pass_bitstream_generated"
close $manifest
puts "BIT/LTX generated under $build; no hardware was programmed."
