# Reuse generated Aurora/VIO IP from a runtime project while probing capacity.
# Arguments: existing_runtime.xpr CAPACITY [synth|implement]
if {[llength $argv]<2 || [llength $argv]>3} {error "Expected RUNTIME_XPR CAPACITY ?synth|implement?"}
lassign $argv xpr capacity action
if {$action eq ""} {set action implement}
if {$capacity<3 || $capacity>30 || $capacity%3!=0 || $action ni {synth implement}} {error "Invalid runtime capacity/action"}
open_project $xpr
if {[llength [get_ips runtime_vio]]!=1} {error "A runtime_vio project is required"}
set root [file normalize [file join [file dirname [info script]] ..]]
set local [expr {$capacity/3}]
set profile rag_m2_n${capacity}_b0_l${local}_d6_r2_c128_runtime
set build [file join $root build $profile]
file mkdir $build
# Isolate Vivado temporary files when comparing capacities concurrently.
cd $build
set part xc7a35tcsg325-2
set_property generic "G_MODE=2 G_NODES=$capacity G_NODE_BASE=0 G_LOCAL_NODES=$local G_DATA_BYTES=6 G_REF_BYTES=2 G_RUN_CYCLES=128 G_RUNTIME_CONFIG=true G_FIFO_WORDS=128 G_VLINK_FIFO_WORDS=64" [current_fileset]
update_compile_order -fileset sources_1
set f [open [file join $build build_manifest.txt] w]
puts $f "family=RAG\nruntime_config=1\ncapacity=$capacity\nlocal_capacity=$local\nN=$capacity\nnode_base=0\nlocal_nodes=$local\nD=6\nR=2\nrun_cycles=128\npart=$part\nVivado=[version -short]\nfifo_words=128\nvlink_fifo_words=64\nstatus=project_generated_not_implemented"
close $f
# Use the common acceptance checks without recreating IP or changing old images.
set stream [open [file join $root scripts build.tcl] r]
set implementation [read $stream]
close $stream
set implementation [string map [list {source [file join [file dirname [info script]] create_project.tcl]} {}] $implementation]
if {$action eq "synth"} {set ::env(OBSIDIAN_SYNTH_ONLY) 1} else {unset -nocomplain ::env(OBSIDIAN_SYNTH_ONLY)}
eval $implementation
