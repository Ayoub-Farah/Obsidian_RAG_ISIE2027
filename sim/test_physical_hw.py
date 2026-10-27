"""Run the real Tcl collector against an in-memory VIO fixture, without Vivado/JTAG."""
from pathlib import Path
import json,tempfile,unittest
try:import tkinter
except ImportError:tkinter=None
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipIf(tkinter is None,'Python Tcl interpreter unavailable')
class CollectorTests(unittest.TestCase):
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
proc obsidian_hw::write_output {v index value} {
 if {$index!=3} {error "Unexpected mutation in read-only collector"}
 set ::mock_address [expr 0x$value]
}
proc obsidian_hw::read_input {v index} {
 if {$index==0} {return 5048030000000000000000000000000000000000000000000000000000040100}
 if {$index!=1} {error "Unexpected probe read"}
 set value [lindex $::mock_words $::mock_address]
 if {$::mock_address==0} {
  incr ::mock_reads_zero
  if {$::mock_change && $::mock_reads_zero>1} {return 0000000000000001}
 }
 return $value
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

if __name__=='__main__':unittest.main()
