# Same six asynchronous reset pins as the verified Obsidian reset chains.
# Structural assertions run in build_physical.tcl, outside XDC interpretation.
set_false_path -to [get_pins -hierarchical -filter {NAME =~ u_optical/reset_pipe_reg*/PRE || NAME =~ u_optical/reset_pipe_reg*/CLR || NAME =~ reset_pipe_reg*/PRE || NAME =~ reset_pipe_reg*/CLR}]
