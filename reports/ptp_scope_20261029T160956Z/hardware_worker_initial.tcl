# Report-local worker. Run only in Vivado; never programs/resets/stops PTP.
# Requests must be atomically renamed to hardware_rpc/request.txt.
# One line: UNIQUE_ID status | UNIQUE_ID observe SERIAL GLOBAL_NODE | UNIQUE_ID exit.
namespace eval ::ptp_scope_worker {
 variable worker_dir [file normalize [file dirname [info script]]]
 variable worker_root [file normalize [file join $worker_dir ../..]]
 variable worker_rpc [file join $worker_dir hardware_rpc]
 variable worker_targets {OBS001A OBS003A OBS002A}
 variable worker_first [dict create OBS001A 0 OBS003A 3 OBS002A 6]
 variable worker_config 0xb548f1927173517b
 variable worker_rejected 0
}
proc ::ptp_scope_worker::utc {} {
 return [clock format [clock seconds] -gmt 1 -format {%Y-%m-%dT%H:%M:%SZ}]
}
proc ::ptp_scope_worker::quote {worker_text} {
 set worker_result "\""
 foreach worker_char [split $worker_text ""] {
  scan $worker_char %c worker_code
  if {$worker_char eq "\""} {append worker_result {\"}} elseif {$worker_char eq "\\"} {
   append worker_result {\\}
  } elseif {$worker_code<32} {append worker_result [format {\u%04x} $worker_code]} else {
   append worker_result $worker_char
  }
 }
 append worker_result "\""
 return $worker_result
}
proc ::ptp_scope_worker::object {worker_pairs} {
 set worker_fields {}
 foreach {worker_key worker_value} $worker_pairs {
  lappend worker_fields "[quote $worker_key]:$worker_value"
 }
 return "\{[join $worker_fields ,]\}"
}
proc ::ptp_scope_worker::strings {worker_values} {
 set worker_encoded {}
 foreach worker_value $worker_values {lappend worker_encoded [quote $worker_value]}
 return "\[[join $worker_encoded ,]\]"
}
proc ::ptp_scope_worker::atomic {worker_path worker_json {worker_replace 0}} {
 if {!$worker_replace && [file exists $worker_path]} {error "Receipt already exists: $worker_path"}
 set worker_temp "$worker_path.[pid].tmp"
 set worker_channel [open $worker_temp {WRONLY CREAT EXCL}]
 fconfigure $worker_channel -encoding utf-8 -translation lf
 puts $worker_channel $worker_json
 close $worker_channel
 if {$worker_replace} {file rename -force $worker_temp $worker_path} else {
  file rename $worker_temp $worker_path
 }
}
proc ::ptp_scope_worker::board {worker_serial} {
 variable worker_first
 variable worker_config
 set worker_started [utc]
 set worker_start_ms [clock milliseconds]
 set worker_code [catch {
  set worker_vio [::ptp_hw::select $worker_serial]
  foreach worker_port {0 2 3 4 5} {
   set worker_input($worker_port) [expr 0x[::obsidian_hw::read_input $worker_vio $worker_port]]
  }
  foreach worker_port {7 8 9 10} {
   set worker_probe [::obsidian_hw::vio_probe $worker_vio out $worker_port]
   set worker_output($worker_port) [expr 0x[::obsidian_hw::read_probe $worker_probe]]
  }
  set worker_status $worker_input(0)
  set worker_expected_first [dict get $worker_first $worker_serial]
  set worker_role [expr {$worker_expected_first/3}]
  set worker_errors {}
  if {($worker_status>>232)!=0x505401} {lappend worker_errors "PTP signature mismatch"}
  if {($worker_status&25)!=25} {lappend worker_errors "Configured/running/locked required"}
  if {$worker_status&4194} {lappend worker_errors "Configuration error, holdover, core fault or halt"}
  if {(($worker_status>>16)&65535)!=3 || (($worker_status>>32)&65535)!=9} {
   lappend worker_errors "Expected K=3/N=9"
  }
  if {(($worker_status>>8)&3)!=$worker_role || (($worker_status>>48)&65535)!=$worker_expected_first} {
   lappend worker_errors "Role/first-node mismatch"
  }
  if {$worker_input(2)!=$worker_config} {lappend worker_errors "Active configuration ID mismatch"}
  if {$worker_input(4)!=3} {lappend worker_errors "Both Aurora links must be up"}
  if {$worker_input(5)!=0} {lappend worker_errors "Current Aurora hard/soft/frame error"}
  if {$worker_output(7)!=$worker_role} {lappend worker_errors "Role output mismatch"}
  if {$worker_output(9)!=0} {lappend worker_errors "Observation apply remains asserted"}
  if {$worker_input(3)&(1<<17)} {lappend worker_errors "Observation selection error"}
  if {$worker_output(10)} {
   set worker_active [expr {$worker_input(3)&65535}]
   if {!($worker_input(3)&(1<<16)) || $worker_active!=$worker_output(8) ||
       $worker_active<$worker_expected_first || $worker_active>=$worker_expected_first+3} {
    lappend worker_errors "Enabled observation is invalid or differs from its selection"
   }
  }
  set worker_nominal [expr {[llength $worker_errors]==0}]
  set worker_fields [list serial [quote $worker_serial] \
   host_started_utc [quote $worker_started] host_finished_utc [quote [utc]] \
   host_started_ms $worker_start_ms host_finished_ms [clock milliseconds] \
   expected_role $worker_role expected_first $worker_expected_first \
   status_hex [quote [format %064llx $worker_status]] \
   config_id_hex [quote [format %016llx $worker_input(2)]] \
   observer_hex [quote [format %08x $worker_input(3)]] \
   links_hex [quote [format %x $worker_input(4)]] \
   phy_errors_hex [quote [format %02x $worker_input(5)]] \
   nominal [expr {$worker_nominal ? "true" : "false"}] errors [strings $worker_errors]]
  foreach worker_port {7 8 9 10} {
   lappend worker_fields [format output%d_hex $worker_port] [quote [format %x $worker_output($worker_port)]]
  }
  set worker_result [dict create nominal $worker_nominal json [object $worker_fields]]
 } worker_result worker_options]
 catch {close_hw_target}
 if {$worker_code} {return -options $worker_options $worker_result}
 return $worker_result
}
proc ::ptp_scope_worker::all_boards {} {
 variable worker_targets
 set worker_cards {}
 set worker_nominal 1
 foreach worker_serial $worker_targets {
  if {[catch {board $worker_serial} worker_result]} {
   set worker_nominal 0
   lappend worker_cards [object [list serial [quote $worker_serial] nominal false error [quote $worker_result]]]
  } else {
   if {![dict get $worker_result nominal]} {set worker_nominal 0}
   lappend worker_cards [dict get $worker_result json]
  }
 }
 return [dict create nominal $worker_nominal json "\[[join $worker_cards ,]\]"]
}
proc ::ptp_scope_worker::dispatch {worker_request} {
 variable worker_rpc
 variable worker_first
 variable worker_rejected
 set worker_started [utc]
 set worker_begin_ms [clock milliseconds]
 set worker_id ""
 if {![regexp {^([A-Za-z0-9][A-Za-z0-9_-]{0,63})([ \t]|$)} $worker_request _ worker_id]} {
  set worker_id "rejected_[clock microseconds]_[incr worker_rejected]"
 }
 set worker_receipt [file join $worker_rpc "$worker_id.json"]
 if {[file exists $worker_receipt]} {
  set worker_id "duplicate_[clock microseconds]_[incr worker_rejected]"
  set worker_receipt [file join $worker_rpc "$worker_id.json"]
  set worker_duplicate 1
 } else {set worker_duplicate 0}
 set worker_cards {[]}
 set worker_exit 0
 set worker_code [catch {
  if {$worker_duplicate} {error "Duplicate request ID; command was not executed"}
  if {[regexp {^[A-Za-z0-9][A-Za-z0-9_-]{0,63}[ \t]+status$} $worker_request]} {
   set worker_result [all_boards]
   set worker_cards [dict get $worker_result json]
   if {![dict get $worker_result nominal]} {error "One or more boards are not nominal"}
  } elseif {[regexp {^[A-Za-z0-9][A-Za-z0-9_-]{0,63}[ \t]+observe[ \t]+(OBS001A|OBS003A|OBS002A)[ \t]+([0-8])$} \
              $worker_request _ worker_serial worker_node]} {
   set worker_local_first [dict get $worker_first $worker_serial]
   if {$worker_node<$worker_local_first || $worker_node>=$worker_local_first+3} {
    error "Requested global node does not belong to $worker_serial"
   }
   # Gate the write on the complete current configuration and health.
   set worker_result [all_boards]
   set worker_cards [dict get $worker_result json]
   if {![dict get $worker_result nominal]} {error "Observation write refused: board state is not nominal"}
   ::ptp_hw::observe $worker_serial $worker_node
   set worker_result [all_boards]
   set worker_cards [dict get $worker_result json]
   if {![dict get $worker_result nominal]} {error "One or more boards are not nominal after observation"}
  } elseif {[regexp {^[A-Za-z0-9][A-Za-z0-9_-]{0,63}[ \t]+exit$} $worker_request]} {
   set worker_exit 1
  } else {error "Only 'ID status', 'ID observe SERIAL GLOBAL_NODE', or 'ID exit' are allowed"}
 } worker_error]
 set worker_fields [list schema [quote ptp_scope_hardware_rpc_v1] request_id [quote $worker_id] \
  request [quote $worker_request] status [quote [expr {$worker_code ? "error" : "ok"}]] \
  host_started_utc [quote $worker_started] host_finished_utc [quote [utc]] \
  host_started_ms $worker_begin_ms host_finished_ms [clock milliseconds] cards $worker_cards]
 if {$worker_code} {lappend worker_fields error [quote $worker_error]}
 atomic $worker_receipt [object $worker_fields]
 puts "PTP_SCOPE_RPC $worker_id [expr {$worker_code ? "error" : "ok"}]"
 flush stdout
 return $worker_exit
}
proc ::ptp_scope_worker::run {} {
 variable worker_root
 variable worker_rpc
 variable worker_targets
 file mkdir $worker_rpc
 # Source in the global namespace, as expected by the production helpers.
 uplevel #0 [list source [file join $worker_root scripts ptp_hw.tcl]]
 set ::ptp_hw::targets $worker_targets
 set ::ptp_hw::ltx [file join $worker_root build ptp_capacity_search k3_route obsidian_ptp.ltx]
 set ::ptp_hw::timeout_ms 10000
 if {![file exists $::ptp_hw::ltx]} {error "Missing K3 probe file"}
 if {[file exists [file join $worker_rpc ready.json]]} {
  file rename [file join $worker_rpc ready.json] [file join $worker_rpc "ready_previous_[clock microseconds].json"]
 }
 set worker_opened 0
 set worker_code [catch {
  open_hw_manager
  set worker_opened 1
  connect_hw_server
  atomic [file join $worker_rpc ready.json] [object [list schema [quote ptp_scope_hardware_rpc_v1] \
   status [quote ready] host_time_utc [quote [utc]] pid [pid] targets [strings $worker_targets] \
   ltx [quote $::ptp_hw::ltx]]]
  puts "PTP_SCOPE_WORKER_READY $worker_rpc"
  flush stdout
  set worker_request_path [file join $worker_rpc request.txt]
  set worker_quit 0
  while {!$worker_quit} {
   if {[file exists $worker_request_path]} {
    set worker_claim "$worker_request_path.[pid].processing"
    file rename $worker_request_path $worker_claim
    set worker_channel [open $worker_claim r]
    fconfigure $worker_channel -encoding utf-8
    set worker_requests [read $worker_channel]
    close $worker_channel
    file delete $worker_claim
    foreach worker_line [split $worker_requests "\n"] {
     set worker_line [string trim $worker_line]
     if {$worker_line eq ""} {continue}
     set worker_quit [dispatch $worker_line]
     if {$worker_quit} {break}
    }
   }
   if {!$worker_quit} {after 100}
  }
 } worker_result worker_options]
 catch {close_hw_target}
 if {$worker_opened} {catch {close_hw_manager}}
 if {$worker_code} {return -options $worker_options $worker_result}
 puts PTP_SCOPE_WORKER_CLOSED
 flush stdout
}
::ptp_scope_worker::run
