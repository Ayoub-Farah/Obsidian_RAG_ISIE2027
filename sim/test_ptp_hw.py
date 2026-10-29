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


if __name__=='__main__':unittest.main()
