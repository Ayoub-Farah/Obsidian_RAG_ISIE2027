# Read-only checkpoint analysis; reports only, no implementation/programming.
if {[llength $argv]!=2} {error "Expected CHECKPOINT OUTPUT_PREFIX"}
lassign $argv checkpoint prefix
open_checkpoint $checkpoint
report_timing_summary -report_unconstrained -file ${prefix}_timing_summary.rpt
report_timing -delay_type max -max_paths 20 -nworst 1 -file ${prefix}_paths.rpt
report_utilization -file ${prefix}_utilization.rpt
puts "CHECKPOINT_REPORT_COMPLETE"
