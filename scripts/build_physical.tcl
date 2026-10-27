set from_synth 0
set from_routed 0
if {[info exists ::env(OBSIDIAN_FROM_SYNTH)] && $::env(OBSIDIAN_FROM_SYNTH) eq "1"} {set from_synth 1}
if {[info exists ::env(OBSIDIAN_FROM_ROUTED)] && $::env(OBSIDIAN_FROM_ROUTED) eq "1"} {set from_routed 1}
if {$from_synth || $from_routed} {
 set root [file normalize [file join [file dirname [info script]] ..]]
 set build [file join $root build physical_runtime];set part xc7a35tcsg325-2
 open_project [file join $build physical_runtime.xpr]
 if {$from_routed} {open_checkpoint [file join $build obsidian_benchmark_routed.dcp]} else {open_checkpoint [file join $build obsidian_benchmark_synth.dcp]}
 read_xdc [file join $root constraints physical_reset_cdc.xdc]
} else {source [file join [file dirname [info script]] create_physical_project.tcl]}
# Reuse the established acceptance gates without recreating legacy profiles.
set f [open [file join $root scripts build.tcl] r]
set implementation [read $f];close $f
set implementation [string map [list {source [file join [file dirname [info script]] create_project.tcl]} {} \
 {synth_design -top obsidian_benchmark_top} {synth_design -top obsidian_physical_top}] $implementation]
# Assert the exact reset exception and fail before implementation if a chain
# disappears or its ASYNC_REG protection is lost.
set reset_checks {
set reset_cells [get_cells -quiet -hierarchical -filter {NAME =~ u_optical/reset_pipe_reg* || NAME =~ reset_pipe_reg*}]
if {[llength $reset_cells]!=6} {error "Expected exactly six Obsidian reset synchronizer registers"}
foreach c $reset_cells {if {![get_property ASYNC_REG $c]} {error "Missing ASYNC_REG on $c"}}
set reset_pins [get_pins -of_objects $reset_cells -filter {REF_PIN_NAME == PRE || REF_PIN_NAME == CLR}]
if {[llength $reset_pins]!=6} {error "Expected exactly six asynchronous reset controls"}
}
set implementation [string map [list "\nopt_design\n" "\n$reset_checks\nopt_design\n"] $implementation]
if {$from_synth} {
 set implementation [string map [list {synth_design -top obsidian_physical_top -part $part -generic [get_property generic [current_fileset]]} {}] $implementation]
}
if {$from_routed} {
 # Preserve the established routed-timing refinement before acceptance gates.
 set start [string first {set routed_paths [get_timing_paths} $implementation]
 if {$start<0} {error "Cannot locate implementation acceptance gates"}
 set implementation "$reset_checks\n[string range $implementation $start end]"
}
eval $implementation
