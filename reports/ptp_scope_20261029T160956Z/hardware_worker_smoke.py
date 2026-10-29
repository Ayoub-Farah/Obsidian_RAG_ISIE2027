"""Mock-only smoke test; imports no hardware libraries and launches no tools."""
from pathlib import Path
import json
import sys
import tempfile
import tkinter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sim.test_ptp_hw import PtpOutputCache


def main():
    t = PtpOutputCache().interpreter()
    source = Path(__file__).with_name('hardware_worker.tcl').read_text()
    t.eval(source.rsplit('\n::ptp_scope_worker::run', 1)[0])
    t.eval('''
set worker_mock_serial OBS001A
set worker_mock_fault 0
set worker_mock_opens 0
set worker_mock_connections 0
set worker_mock_closes 0
set worker_mock_refreshes 0
set worker_mock_available {OBS001A OBS003A}
set worker_mock_enabled 1
set worker_mock_bad_disable 0
rename commit_hw_vio worker_mock_original_commit
proc commit_hw_vio {vio} {
 set before $::mock_vio::hardware(9)
 worker_mock_original_commit $vio
 if {!$before && $::mock_vio::hardware(9)} {
  set ::worker_mock_enabled $::mock_vio::hardware(10)
  if {$::worker_mock_bad_disable && !$::worker_mock_enabled} {
   incr ::mock_vio::active_observer
  }
 }
}
proc open_hw_manager {} {incr ::worker_mock_opens}
proc connect_hw_server {} {incr ::worker_mock_connections}
proc refresh_hw_server {} {incr ::worker_mock_refreshes}
proc close_hw_manager {} {incr ::worker_mock_closes}
proc get_hw_targets {args} {
 set serial [file tail [lindex $args end]]
 return [expr {$serial in $::worker_mock_available ? $serial : ""}]
}
proc open_hw_target {serial} {
 if {$serial ni $::worker_mock_available} {error "Attempted to open unavailable card"}
 set ::worker_mock_serial $serial
}
rename get_property worker_mock_original_property
proc get_property {property object} {
 set first [dict get {OBS001A 0 OBS003A 3 OBS002A 6} $::worker_mock_serial]
 set role [expr {$first/3}]
 if {$property eq "INPUT_VALUE"} {
  switch -- $object {
   in0 {return [format %064llx [expr {(0x505401<<232)|($first<<48)|(9<<32)|(3<<16)|($role<<8)|25|$::worker_mock_fault}]]}
   in2 {return b548f1927173517b}
   in3 {
    set node [expr {$first ? $first+2 : $::mock_vio::active_observer}]
    set enabled [expr {$first ? 1 : $::worker_mock_enabled}]
    return [format %x [expr {$node|($enabled<<16)}]]
   }
  }
 }
 if {$property eq "OUTPUT_VALUE"} {
  if {$object eq "out7"} {return $role}
  if {$object eq "out8" && $first} {return [expr {$first+2}]}
  if {$object eq "out10" && $first} {return 1}
 }
 return [worker_mock_original_property $property $object]
}
''')
    with tempfile.TemporaryDirectory() as directory:
        rpc = Path(directory)
        t.call('set', 'ptp_scope_worker::worker_rpc', str(rpc))
        t.call('set', 'ptp_scope_worker::worker_root', str(ROOT))

        def dispatch(request):
            t.call('ptp_scope_worker::dispatch', request)
            return json.loads((rpc / (request.split()[0] + '.json')).read_text())

        status = dispatch('initial status')
        assert status['status'] == 'ok' and len(status['cards']) == 3
        assert status['health_scope'] == 'connected_boards_only'
        assert status['expected_connected'] == ['OBS001A', 'OBS003A']
        assert [c['expected_first'] for c in status['cards'][:2]] == [0, 3]
        assert all(c['nominal'] and len(c['status_hex']) == 64 for c in status['cards'][:2])
        assert status['cards'][2] == dict(serial='OBS002A', available=False,
                                         expected_connected=False, nominal=None, error=None)
        assert not t.splitlist(t.call('set', 'mock_vio::commits'))
        assert dispatch('wrong observe OBS003A 0')['status'] == 'error'
        assert dispatch('injection status; reset_hw_vio_outputs')['status'] == 'error'
        assert not t.splitlist(t.call('set', 'mock_vio::commits'))
        observed = dispatch('select_ref observe OBS001A 0')
        assert observed['status'] == 'ok'
        assert int(observed['cards'][0]['observer_hex'], 16) == 1 << 16
        assert all(int(c['output9_hex'], 16) == 0 for c in observed['cards'] if c['available'])
        pre_disable = PtpOutputCache.state(t)
        history_count = len(t.splitlist(t.call('set', 'mock_vio::commits')))
        disabled = dispatch('disable_ref disable OBS001A')
        assert disabled['status'] == 'ok'
        assert disabled['diagnostic']['active_id_before'] == disabled['diagnostic']['active_id_after'] == 0
        assert disabled['cards'][0]['observer_hex'] == '00000000'
        assert disabled['cards'][0]['output10_hex'] == '0'
        for state in t.splitlist(t.call('set', 'mock_vio::commits'))[history_count:]:
            values = tuple(map(int, t.splitlist(state)))
            assert all(values[i] == pre_disable[i] for i in range(13) if i not in (9, 10))
        assert dispatch('reenable observe OBS001A 0')['status'] == 'ok'
        assert int(t.call('set', 'worker_mock_enabled')) == 1
        t.call('set', 'worker_mock_bad_disable', 1)
        changed_id = dispatch('disable_bad_id disable OBS001A')
        assert changed_id['status'] == 'error' and 'ID changed' in changed_id['error']
        t.call('set', 'worker_mock_bad_disable', 0)
        assert dispatch('recover_observer observe OBS001A 0')['status'] == 'ok'
        before = t.call('set', 'mock_vio::commits')
        t.call('set', 'worker_mock_fault', 64)
        failed = dispatch('fault observe OBS001A 2')
        assert failed['status'] == 'error' and all(not c['nominal'] for c in failed['cards'])
        assert t.call('set', 'mock_vio::commits') == before
        assert dispatch('disable_fault disable OBS001A')['status'] == 'error'
        assert t.call('set', 'mock_vio::commits') == before
        t.call('set', 'worker_mock_fault', 0)
        assert dispatch('recovered status')['status'] == 'ok'
        t.call('set', 'worker_mock_available', ('OBS001A', 'OBS002A'))
        missing = dispatch('missing_expected status')
        assert missing['status'] == 'error'
        assert missing['cards'][1]['available'] is False
        assert missing['cards'][1]['nominal'] is None
        expected_file = rpc / 'expected_targets.txt'
        for invalid in ('OBS001A\nOBS001A\n', 'OBS003A\nOBS002A\n',
                        'OBS001A\nUNKNOWN\n', 'OBS001A\nOBS003A\nOBS002A\n'):
            expected_file.write_text(invalid, encoding='utf-8')
            try:
                t.call('ptp_scope_worker::load_expected')
            except tkinter.TclError:
                pass
            else:
                raise AssertionError('Invalid expected connected set accepted')
        expected_file.write_text('\ufeffOBS001A\nOBS002A\n', encoding='utf-8')
        t.call('ptp_scope_worker::load_expected')
        swapped = dispatch('swapped status')
        assert swapped['status'] == 'ok'
        assert swapped['expected_connected'] == ['OBS001A', 'OBS002A']
        assert swapped['cards'][1]['available'] is False and swapped['cards'][1]['nominal'] is None
        assert dispatch('not_expected observe OBS003A 3')['status'] == 'error'
        assert dispatch('disable_not_expected disable OBS003A')['status'] == 'error'
        assert t.call('set', 'mock_vio::commits') == before
        t.call('ptp_scope_worker::dispatch', 'select_ref observe OBS001A 2')
        assert t.call('set', 'mock_vio::commits') == before
        assert len(list(rpc.glob('duplicate_*.json'))) == 1
        quoted = 'quote " backslash \\ tab\t newline\n control\x01'
        assert json.loads(t.call('ptp_scope_worker::quote', quoted)) == quoted
        (rpc / 'request.txt').write_text('lifecycle status\nquit exit\n', encoding='utf-8')
        t.call('ptp_scope_worker::run')
        ready = json.loads((rpc / 'ready.json').read_text())
        assert ready['status'] == 'ready'
        assert ready['expected_connected'] == ['OBS001A', 'OBS002A']
        assert ready['health_scope'] == 'connected_boards_only'
        assert json.loads((rpc / 'lifecycle.json').read_text())['status'] == 'ok'
        assert json.loads((rpc / 'quit.json').read_text())['status'] == 'ok'
        assert [int(t.call('set', name)) for name in
                ('worker_mock_opens', 'worker_mock_connections', 'worker_mock_closes',
                 'worker_mock_refreshes')] == [1, 1, 1, 1]
        assert not list(rpc.glob('*.tmp'))
    print('PASS: safe disable/re-enable, ID-change detection, unchanged other controls, two-board scope, ownership/health gates, strict commands, JSON/lifecycle; no hardware.')


if __name__ == '__main__':
    main()
