source [file join [file dirname [info script]] create_ptp_project.tcl]
# Keep the physical profile's setup/hold/bus-skew/DRC acceptance gates.
set ptp_implementation_channel [open [file join $root scripts build.tcl] r]
set implementation [read $ptp_implementation_channel];close $ptp_implementation_channel
set implementation [string map [list \
 {source [file join [file dirname [info script]] create_project.tcl]} {} \
 obsidian_benchmark obsidian_ptp] $implementation]
set ptp_gpio_checks {
foreach port {test_ref_m1_o test_obs_o} {
 set ptp_gpio_paths [get_timing_paths -to [get_ports $port] -max_paths 1]
 if {[llength $ptp_gpio_paths]!=1 || [get_property SLACK [lindex $ptp_gpio_paths 0]]<0} {error "GPIO timing failed: $port"}
 set ptp_gpio_report [file join $build gpio_${port}.rpt]
 report_timing -to [get_ports $port] -max_paths 1 -file $ptp_gpio_report
 set ptp_gpio_channel [open $ptp_gpio_report r]
 set ptp_gpio_text [read $ptp_gpio_channel];close $ptp_gpio_channel
 if {![regexp {Requirement:\s+8\.000ns\s+\(MaxDelay Path} $ptp_gpio_text]} {error "Missing 8 ns register-to-pad constraint: $port"}
}
}
set implementation [string map [list {write_bitstream -force} "$ptp_gpio_checks\nwrite_bitstream -force"] $implementation]
eval $implementation
