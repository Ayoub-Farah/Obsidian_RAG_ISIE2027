# Hardware Manager property-aware VIO probe access.
# AMD UG912 HW_PROBE documents TYPE=vio_input/vio_output and PROBE_PORT.
# Probe NAME can be the connected net, not the IP's probe_inN/probe_outN pin.
# https://docs.amd.com/r/en-US/ug912-vivado-properties/HW_PROBE
# https://docs.amd.com/r/en-US/ug912-vivado-properties/HW_VIO
namespace eval obsidian_hw {}
proc obsidian_hw::property_names {object} {
 set result {}
 foreach name [list_property $object] {lappend result [string toupper $name]}
 return $result
}
proc obsidian_hw::direction {probe} {
 set names [property_names $probe]
 if {"TYPE" in $names} {
  set type [string tolower [string trim [get_property TYPE $probe]]]
  if {$type eq "vio_input"} {return in}
  if {$type eq "vio_output"} {return out}
  if {$type ne ""} {error "Probe $probe is not a VIO input/output (TYPE=$type)"}
 }
 # Strict fallback for tool versions lacking TYPE: an entire final path
 # component must be probe_inN or probe_outN. Never substring-match port 0/10.
 if {"NAME" in $names && [regexp {(^|/)probe_(in|out)([0-9]+)$} [get_property NAME $probe] _ prefix direction index]} {
  return $direction
 }
 error "Cannot determine VIO probe direction for $probe; inspect report_property -all"
}
proc obsidian_hw::vio_probe {vio direction index} {
 if {$direction ni {in out} || ![string is integer -strict $index] || $index<0} {
  error "Expected VIO direction in/out and a nonnegative probe index"
 }
 set expected [expr {$direction eq "in" ? "vio_input" : "vio_output"}]
 set exact {};set fallback {}
 foreach probe [get_hw_probes -of_objects $vio] {
  set names [property_names $probe]
  set type ""
  if {"TYPE" in $names} {set type [string tolower [string trim [get_property TYPE $probe]]]}
  if {$type ne "" && $type ne $expected} {continue}
  if {$type eq $expected && "PROBE_PORT" in $names} {
   set port [get_property PROBE_PORT $probe]
   if {![string is integer -strict $port]} {error "Invalid PROBE_PORT for $probe: $port"}
   if {$port==$index} {lappend exact $probe}
   continue
  }
  if {"NAME" in $names && [regexp {(^|/)probe_(in|out)([0-9]+)$} [get_property NAME $probe] _ prefix named_direction named_index]} {
   if {$named_direction eq $direction && $named_index==$index} {lappend fallback $probe}
  }
 }
 if {[llength $exact]>1} {error "Ambiguous VIO $direction port $index: $exact"}
 if {[llength $exact]==1} {return [lindex $exact 0]}
 if {[llength $fallback]!=1} {error "Cannot uniquely resolve VIO $direction port $index (fallback=$fallback); inspect report_property -all"}
 return [lindex $fallback 0]
}
proc obsidian_hw::read_probe {probe} {
 set property [expr {[direction $probe] eq "in" ? "INPUT_VALUE" : "OUTPUT_VALUE"}]
 if {$property ni [property_names $probe]} {error "Probe $probe lacks $property"}
 return [get_property $property $probe]
}
proc obsidian_hw::read_input {vio index} {
 return [read_probe [vio_probe $vio in $index]]
}
proc obsidian_hw::write_output {vio index value} {
 set probe [vio_probe $vio out $index]
 if {"OUTPUT_VALUE" ni [property_names $probe]} {error "Probe $probe lacks OUTPUT_VALUE"}
 set_property OUTPUT_VALUE $value $probe
 commit_hw_vio $vio
}
