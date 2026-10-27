# Host-only mocks: does not connect to Vivado, hardware, or a server.
set scripts_dir [file dirname [info script]]
set properties [dict create]
foreach direction {in out} {
 foreach index {0 1 2 3 4 5 10} {
  set object "p_${direction}${index}"
  set type [expr {$direction eq "in" ? "vio_input" : "vio_output"}]
  set value_property [expr {$direction eq "in" ? "INPUT_VALUE" : "OUTPUT_VALUE"}]
  # NAME deliberately identifies connected nets, never probe_inN/probe_outN.
  dict set properties $object [dict create TYPE $type PROBE_PORT $index NAME "design/connected_${direction}_net_${index}" $value_property ab]
 }
}
proc list_property {object} {return [dict keys [dict get $::properties $object]]}
proc get_property {property object} {return [dict get $::properties $object $property]}
proc get_hw_probes {args} {return [dict keys $::properties]}
set output_writes 0
proc set_property {property value object} {
 if {$property eq "OUTPUT_VALUE"} {
  if {[dict get $::properties $object TYPE] ne "vio_output"} {error "Attempted write to input"}
  dict set ::properties $object $property $value
  incr ::output_writes
 }
}
proc commit_hw_vio {args} {}
source [file join $scripts_dir hw_helpers.tcl]
if {[obsidian_hw::vio_probe vio0 in 0] ne "p_in0"} {error "Wrong input0"}
if {[obsidian_hw::vio_probe vio0 out 0] ne "p_out0"} {error "Wrong output0"}
if {[obsidian_hw::vio_probe vio0 in 10] ne "p_in10"} {error "Port10 confused with port0"}
if {[obsidian_hw::vio_probe vio0 out 10] ne "p_out10"} {error "Output10 confused with output0"}
obsidian_hw::write_output vio0 0 ef
if {[obsidian_hw::read_probe p_out0] ne "ef"} {error "Wrong output readback"}
if {[obsidian_hw::read_input vio0 0] ne "ab"} {error "Wrong input read"}
# Verify strict fallback only when properties needed for primary lookup are absent.
set saved_properties $properties
set properties [dict create a [dict create NAME top/probe_in0 INPUT_VALUE 1] b [dict create NAME top/probe_in10 INPUT_VALUE 2] c [dict create NAME top/probe_out0 OUTPUT_VALUE 3]]
if {[obsidian_hw::vio_probe vio0 in 0] ne "a" || [obsidian_hw::vio_probe vio0 in 10] ne "b" || [obsidian_hw::vio_probe vio0 out 0] ne "c"} {error "Strict fallback failed"}
if {![catch {obsidian_hw::vio_probe vio0 out 10}]} {error "Missing port was guessed"}
set properties $saved_properties
dict set properties duplicate [dict get $properties p_in0]
if {![catch {obsidian_hw::vio_probe vio0 in 0}]} {error "Ambiguous port accepted"}
dict unset properties duplicate
# Exercise both caller scripts with connected-net names and property checking.
proc open_hw_manager {} {}
proc connect_hw_server {} {}
proc get_hw_targets {args} {return cable0}
proc open_hw_target {args} {}
proc get_hw_devices {args} {return device0}
proc refresh_hw_device {args} {}
proc get_hw_vios {args} {
 if {$args ne {-of_objects device0}} {error "Unexpected VIO selection: $args"}
 return vio0
}
proc get_hw_ilas {args} {
 if {$args ne {-of_objects device0}} {error "Unexpected ILA selection: $args"}
 return ila0
}
proc refresh_hw_vio {args} {}
proc upload_hw_ila_data {args} {return data0}
proc write_hw_ila_data {args} {}
proc version {args} {return mocked_2025.2}
set fixture_dir [file normalize [file join $scripts_dir .. build hw_helper_test]]
file mkdir $fixture_dir
set ltx [file join $fixture_dir fake.ltx]
close [open $ltx w]
set argv [list $ltx $fixture_dir device0 read]
set output_writes 0
source [file join $scripts_dir capture.tcl]
if {$output_writes!=0} {error "Passive capture drove output probes"}
set argv [list $ltx [file join $fixture_dir log.json] device0 A]
source [file join $scripts_dir dump_log.tcl]
if {$output_writes!=514} {error "Expected stop/start controls and 512 address writes: $output_writes"}
puts "PASS: property-aware VIO selection, connected-net names, distinct in/out0+10, strict fallback, ambiguity rejection, passive output readback, journal dump. Host mocks only."
