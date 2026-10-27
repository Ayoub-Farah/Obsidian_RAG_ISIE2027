# Async assertion / synchronous release reset chains (three FDPEs each).
# clk50 and Aurora USER_CLK have no common primary clock. Their phase cannot
# define a recovery/removal budget at the asynchronous preset inputs.
# ASYNC_REG preserves placement of the deassertion chains; their D/C paths
# remain timed at USER_CLK. Do not disable an entire clock pair.
# AMD UG906: Asynchronous Reset Synchronizer; UG903: False Paths.
set benchmark_reset_cells [get_cells -quiet -hierarchical -filter {NAME =~ u_optical/reset_pipe_reg* || NAME =~ reset_pipe_reg*}]
if {[llength $benchmark_reset_cells]!=6} {error "Expected exactly two three-stage reset synchronizers"}
foreach benchmark_reset_cell $benchmark_reset_cells {
 if {![get_property ASYNC_REG $benchmark_reset_cell]} {
  error "Reset exception requires ASYNC_REG: $benchmark_reset_cell"
 }
}
set benchmark_reset_async_pins [get_pins -of_objects $benchmark_reset_cells -filter {REF_PIN_NAME == PRE || REF_PIN_NAME == CLR}]
if {[llength $benchmark_reset_async_pins]!=6} {error "Expected exactly six asynchronous reset control pins"}
set_false_path -to $benchmark_reset_async_pins
