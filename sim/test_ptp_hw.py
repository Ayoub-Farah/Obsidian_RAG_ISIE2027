"""Execute the real PTP Tcl collector with synthetic VIO memory, no JTAG."""
from pathlib import Path
import json
import tempfile
import unittest
try:
    import tkinter
except ImportError:
    tkinter=None

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipIf(tkinter is None,'Python Tcl interpreter unavailable')
class PtpCollector(unittest.TestCase):
    def interpreter(self, change=False):
        t=tkinter.Tcl()
        text=(ROOT/'scripts/ptp_hw.tcl').read_text().replace(
            'source [file join [file dirname [info script]] hw_helpers.tcl]',
            'source {'+(ROOT/'scripts/hw_helpers.tcl').as_posix()+'}')
        t.eval(text.replace('hardware_jtag','unit_test_synthetic'))
        words=['0000000000000000']*24
        words[0]='5054504500010001';words[4]='0000000100030000';words[6]='0000000000000001'
        t.call('set','mock_words',tuple(words))
        t.call('set','mock_change',int(change))
        t.eval('''
set mock_address 0;set mock_reads 0;set acked 0
proc ptp_hw::select {serial} {return $serial}
proc close_hw_target {args} {}
proc refresh_hw_vio {args} {}
proc obsidian_hw::write_output {v port value} {
 if {$port==1} {set ::mock_address [expr 0x$value];return}
 if {$port==12} {if {$value==1} {set ::acked 1};return}
 error "Unexpected collector mutation $port"
}
proc obsidian_hw::read_input {v port} {
 if {$port==0} {return [format %064llx [expr {(0x505401<<232)|(3<<32)|(1<<16)|128|1}]]}
 if {$port==1} {
  if {$::mock_address==32768} {
   incr ::mock_reads
   if {$::mock_change && $::mock_reads>1} {return 0}
  }
  return [lindex $::mock_words [expr {$::mock_address-32768}]]
 }
 error "Unexpected collector read"
}
''')
        return t

    def test_double_read_json_and_ack_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=self.interpreter();path=Path(tmp)/'page.json'
            t.call('ptp_hw::collect','MOCK_A',str(path))
            page=json.loads(path.read_text())
            self.assertEqual(len(page['snapshot_words']),24)
            self.assertEqual(page['event_words'],[])
            self.assertEqual(page['source'],'unit_test_synthetic')
            self.assertEqual(t.call('set','acked'),1)
            with self.assertRaises(tkinter.TclError):t.call('ptp_hw::collect','MOCK_A',str(path))

    def test_changed_page_is_not_acked(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=self.interpreter(change=True);path=Path(tmp)/'page.json'
            with self.assertRaises(tkinter.TclError):t.call('ptp_hw::collect','MOCK_A',str(path))
            self.assertFalse(path.exists());self.assertEqual(int(t.call('set','acked')),0)

    def test_wait_requires_every_local_lock_running_without_holdover(self):
        t=self.interpreter()
        t.eval('set ptp_hw::targets {A B C};set ptp_hw::timeout_ms 1;proc ptp_hw::status {serial} {return 24}')
        t.call('ptp_hw::wait_running')
        t.eval('proc ptp_hw::status {serial} {if {$serial eq "C"} {return 56};return 24}')
        with self.assertRaises(tkinter.TclError):t.call('ptp_hw::wait_running')
        t.eval('proc ptp_hw::status {serial} {return 64}')
        with self.assertRaises(tkinter.TclError):t.call('ptp_hw::wait_running')
        t.eval('proc ptp_hw::status {serial} {return 1029}')
        t.call('ptp_hw::wait_running',1)
        with self.assertRaises(tkinter.TclError):t.call('ptp_hw::wait_running',0)


@unittest.skipIf(tkinter is None,'Python Tcl interpreter unavailable')
class PtpOutputCache(unittest.TestCase):
    """A fresh software VIO has defaults; hardware is already observing M3."""

    def interpreter(self):
        t=tkinter.Tcl()
        source=(ROOT/'scripts/ptp_hw.tcl').read_text().replace(
            'source [file join [file dirname [info script]] hw_helpers.tcl]',
            'source {'+(ROOT/'scripts/hw_helpers.tcl').as_posix()+'}')
        t.eval(source)
        t.eval('''
set ptp_hw::ltx synthetic.ltx
namespace eval mock_vio {
 variable defaults;variable hardware;variable software
 array set defaults {0 0 1 0 2 0 3 0 4 0 5 0 6 0 7 3 8 0 9 0 10 0 11 0 12 0}
 array set hardware [array get defaults]
 array set hardware {1 66 2 3735928559 7 0 8 2 10 1}
 array set software [array get defaults]
 variable active_observer 2
 variable refreshes 0
 variable commits {}
}
proc get_hw_targets {args} {return synthetic_target}
proc open_hw_target {args} {}
proc close_hw_target {args} {}
proc current_hw_target {} {return synthetic_target}
proc get_hw_devices {args} {return synthetic_device}
proc get_hw_vios {args} {return synthetic_vio}
proc refresh_hw_device {args} {
 # Model rediscovery with a stale software cache, not a hardware reset.
 array set ::mock_vio::software [array get ::mock_vio::defaults]
}
proc refresh_hw_vio {args} {
 if {"-update_output_values" in $args} {
  array set ::mock_vio::software [array get ::mock_vio::hardware]
  incr ::mock_vio::refreshes
 }
}
proc get_hw_probes {args} {
 set probes {}
 foreach direction {in out} count {6 13} {
  for {set index 0} {$index<$count} {incr index} {lappend probes ${direction}$index}
 }
 return $probes
}
proc list_property {probe} {return {TYPE PROBE_PORT INPUT_VALUE OUTPUT_VALUE}}
proc get_property {property object} {
 if {$property eq "PART"} {return xc7a35t}
 if {![regexp {^(in|out)([0-9]+)$} $object _ direction index]} {error "Unknown probe $object"}
 switch -- $property {
  TYPE {return vio_[expr {$direction eq "in" ? "input" : "output"}]}
  PROBE_PORT {return $index}
  OUTPUT_VALUE {return [format %x $::mock_vio::software($index)]}
  INPUT_VALUE {
   switch -- $index {
    0 {return [format %064llx [expr {(0x505401<<232)|(9<<32)|(3<<16)|25}]]}
    1 {return 0123456789abcdef}
    2 {return 12345678}
    3 {return [format %x [expr {$::mock_vio::active_observer|(1<<16)}]]}
    4 {return 3}
    5 {return 0}
   }
  }
 }
 error "Unexpected property $property on $object"
}
proc set_property {property value object} {
 if {$property eq "PROBES.FILE"} {return}
 if {$property ne "OUTPUT_VALUE" || ![regexp {^out([0-9]+)$} $object _ index]} {
  error "Unexpected property write $property on $object"
 }
 set ::mock_vio::software($index) [expr 0x$value]
}
proc commit_hw_vio {v} {
 if {$v ne "synthetic_vio"} {error "Unexpected commit target $v"}
 set was_apply $::mock_vio::hardware(9)
 array set ::mock_vio::hardware [array get ::mock_vio::software]
 if {!$was_apply && $::mock_vio::hardware(9)} {
  set ::mock_vio::active_observer $::mock_vio::hardware(8)
 }
 set state {}
 for {set index 0} {$index<13} {incr index} {lappend state $::mock_vio::hardware($index)}
 lappend ::mock_vio::commits $state
}
''')
        return t

    @staticmethod
    def state(t):
        return tuple(int(t.call('set',f'mock_vio::hardware({i})')) for i in range(13))

    def assert_preserved(self,t,before,changed):
        for state in t.splitlist(t.call('set','mock_vio::commits')):
            state=tuple(map(int,t.splitlist(state)))
            for index,value in enumerate(before):
                if index not in changed:
                    self.assertEqual(state[index],value,f'Unrequested output {index} changed')

    def test_select_refreshes_cache_without_driving_outputs(self):
        t=self.interpreter();before=self.state(t)
        self.assertEqual(t.call('ptp_hw::select','OBS001A'),'synthetic_vio')
        self.assertEqual(int(t.call('set','mock_vio::refreshes')),1)
        self.assertEqual(t.splitlist(t.call('set','mock_vio::commits')),())
        self.assertEqual(self.state(t),before)
        for index,value in enumerate(before):
            self.assertEqual(int(t.call('set',f'mock_vio::software({index})')),value)

    def test_read_address_preserves_running_observer_and_role(self):
        t=self.interpreter();before=self.state(t)
        v=t.call('ptp_hw::select','OBS001A')
        self.assertEqual(t.call('ptp_hw::read_word',v,0x8000),'0123456789abcdef')
        self.assertEqual(self.state(t)[1],0x8000)
        self.assert_preserved(t,before,{1})

    def test_ack_pulse_preserves_every_other_control(self):
        t=self.interpreter();before=self.state(t)
        t.call('ptp_hw::pulse','OBS001A',12)
        states=t.splitlist(t.call('set','mock_vio::commits'))
        self.assertEqual([int(t.splitlist(s)[12]) for s in states],[0,1,0])
        self.assert_preserved(t,before,{12})
        self.assertEqual(self.state(t),before)

    def test_observer_transition_preserves_configuration_and_run_controls(self):
        t=self.interpreter();before=self.state(t)
        t.call('ptp_hw::observe','OBS001A',1)
        self.assertEqual(int(t.call('set','mock_vio::active_observer')),1)
        self.assertEqual(self.state(t)[8:11],(1,0,1))
        self.assert_preserved(t,before,{8,9,10})

    def test_status_poll_reads_current_state_without_commits(self):
        t=self.interpreter();before=self.state(t)
        status=int(t.call('ptp_hw::status','OBS001A'))
        self.assertEqual(status&127,25)  # Configured, running, locked.
        self.assertEqual(t.splitlist(t.call('set','mock_vio::commits')),())
        self.assertEqual(self.state(t),before)


if __name__=='__main__':unittest.main()
