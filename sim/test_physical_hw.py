"""Run the real Tcl collector against an in-memory VIO fixture, without Vivado/JTAG."""
from pathlib import Path
import json,tempfile,unittest
try:import tkinter
except ImportError:tkinter=None
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipIf(tkinter is None,'Python Tcl interpreter unavailable')
class CollectorTests(unittest.TestCase):
    def test_split_vio_input_reassembly_requires_explicit_disjoint_ranges(self):
        t=tkinter.Tcl();t.call('source',str(ROOT/'scripts/hw_helpers.tcl'))
        t.eval('''
set props [dict create hard [dict create TYPE vio_input PROBE_PORT 5 PROBE_PORT_BITS 4 PROBE_PORT_BIT_COUNT 2 INPUT_VALUE 2] frame [dict create TYPE vio_input PROBE_PORT 5 PROBE_PORT_BITS 0 PROBE_PORT_BIT_COUNT 2 INPUT_VALUE 3] soft [dict create TYPE vio_input PROBE_PORT 5 PROBE_PORT_BITS 2 PROBE_PORT_BIT_COUNT 2 INPUT_VALUE 1] role [dict create TYPE vio_output PROBE_PORT 5 PROBE_PORT_BITS 0 PROBE_PORT_BIT_COUNT 2 OUTPUT_VALUE 0]]
proc get_hw_probes {args} {return [dict keys $::props]}
proc list_property {object} {return [dict keys [dict get $::props $object]]}
proc get_property {property object} {return [dict get $::props $object $property]}
''')
        self.assertEqual(t.call('obsidian_hw::read_input','vio',5),'27')
        with self.assertRaises(tkinter.TclError):t.call('obsidian_hw::vio_probe','vio','in',5)
        t.eval('dict set props soft PROBE_PORT_BITS 1')
        with self.assertRaises(tkinter.TclError):t.call('obsidian_hw::read_input','vio',5)
        t.eval('dict set props soft PROBE_PORT_BITS 2;dict unset props frame')
        with self.assertRaises(tkinter.TclError):t.call('obsidian_hw::read_input','vio',5)

    def interpreter(self,output,change=False):
        t=tkinter.Tcl()
        text=(ROOT/'scripts/physical_hw.tcl').read_text()
        text=text.replace('source [file join [file dirname [info script]] hw_helpers.tcl]','source {'+(ROOT/'scripts/hw_helpers.tcl').as_posix()+'}')
        # Fixtures must remain explicitly synthetic, including temporary JSON.
        text=text.replace('hardware_jtag','unit_test_synthetic');t.eval(text)
        words=['0000000000000000']*8192
        words[7168]='5048595300030001';words[7169]='0000000100000000'
        t.call('set','mock_words',tuple(words));t.call('set','mock_address',0);t.call('set','mock_change',int(change));t.call('set','mock_reads_zero',0)
        t.call('set','physical_hw::output',str(output))
        t.eval('''
proc physical_hw::select {serial} {return $serial}
proc refresh_hw_vio {args} {}
proc close_hw_target {args} {}
proc obsidian_hw::vio_probe {v direction index} {
 if {$direction eq "out" && $index==3} {return address_probe}
 if {$direction eq "in" && $index==1} {return journal_probe}
 error "Unexpected probe binding"
}
proc set_property {property value object} {
 if {$property ne "OUTPUT_VALUE" || $object ne "address_probe"} {error "Unexpected mutation in collector"}
 set ::mock_address [expr 0x$value]
}
proc commit_hw_vio {args} {}
proc get_property {property object} {
 if {$property ne "INPUT_VALUE" || $object ne "journal_probe"} {error "Unexpected probe read"}
 set value [lindex $::mock_words $::mock_address]
 if {$::mock_address==0} {
  incr ::mock_reads_zero
  if {$::mock_change && $::mock_reads_zero>1} {return 0000000000000001}
 }
 return $value
}
proc obsidian_hw::read_input {v index} {
 if {$index==0} {return 5048030000000000000000000000000000000000000000000000000000040100}
 error "Unexpected probe read"
}
''')
        return t

    def test_actual_tcl_json_double_read_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            t=self.interpreter(d);t.call('physical_hw::collect_board','MOCK_A','A')
            path=Path(d)/'A_page_00000000.json';data=json.loads(path.read_text())
            self.assertEqual(data['source'],'unit_test_synthetic');self.assertTrue(data['double_read_verified']);self.assertEqual(len(data['words']),8192)
            with self.assertRaises(tkinter.TclError):t.call('physical_hw::collect_board','MOCK_A','A')

    def test_changed_capture_and_wrong_role_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            t=self.interpreter(d,change=True)
            with self.assertRaises(tkinter.TclError):t.call('physical_hw::collect_board','MOCK_A','A')
            self.assertEqual(list(Path(d).iterdir()),[])
            t=self.interpreter(d)
            with self.assertRaises(tkinter.TclError):t.call('physical_hw::collect_board','MOCK_A','B')

    def test_wait_idle_collects_a_final_empty_page_after_stop(self):
        with tempfile.TemporaryDirectory() as d:
            t=self.interpreter(d);t.eval('''
set physical_hw::targets {A B C}
set mock_idle 0
set mock_collected 0
proc physical_hw::status {serial} {if {$::mock_idle} {return 0};return [expr {(1<<18)}]}
proc physical_hw::all_frozen {} {return [expr {!$::mock_idle}]}
proc physical_hw::collect {} {incr ::mock_collected;set ::mock_idle 1}
''')
            t.call('physical_hw::wait_idle');self.assertEqual(int(t.call('set','mock_collected')),1)

    def test_initialize_holds_all_resets_before_releasing_any(self):
        with tempfile.TemporaryDirectory() as d:
            t=self.interpreter(d);t.eval('''
set physical_hw::targets {A B C}
set writes {}
proc obsidian_hw::read_input {v index} {if {$index==4} {return 3};return 0}
proc obsidian_hw::write_output {v index value} {lappend ::writes [list $v $index $value]}
proc physical_hw::status {serial} {return 0}
''')
            t.call('physical_hw::initialize')
            self.assertEqual(t.eval('lmap w $writes {if {[lindex $w 1]!=0} {continue};set w}'),'{A 0 1} {B 0 1} {C 0 1} {A 0 0} {B 0 0} {C 0 0}')
            self.assertEqual(int(t.eval('llength [lmap w $writes {if {[lindex $w 1]==0} {continue};set w}]')),12)
            t.eval('set writes {};proc obsidian_hw::read_input {v index} {if {$index==4} {return 3};return 800}')
            with self.assertRaises(tkinter.TclError):t.call('physical_hw::initialize')
            self.assertEqual(t.eval('set writes'),'')

if __name__=='__main__':unittest.main()
