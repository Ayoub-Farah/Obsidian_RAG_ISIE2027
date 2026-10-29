"""Independent scope-report fixtures: no USB, VISA, JTAG or official captures."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np


ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('scope_report',ROOT/'scripts/ptp_scope_report.py')
report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)


def single(directory,index,shift,*,wide=False,rail=False,mismatched_origin=False):
    step=5e-9 if wide else .5e-9;points=100000 if wide else 4000;origin=0.0 if wide else -1e-6
    time=origin+np.arange(points)*step
    def codes(delay):
        voltage=np.zeros_like(time)
        for start in ((20e-6+cycle*100e-6 for cycle in range(5)) if wide else (0.0,)):
            voltage+=3.3*np.minimum(np.clip((time-start-delay)/20e-9,0,1),np.clip((start+1e-6+delay-time)/20e-9,0,1))
        return np.rint(voltage/.034133+80).astype(np.uint8)
    first,second=codes(0),codes(shift)
    if rail:second[0]=255
    path=directory/f'single_{index:04d}.npz';np.savez_compressed(path,ch1=first,ch2=second)
    metadata=dict(utc=f'2026-10-29T16:00:{index:02d}+00:00',trigger_state='STOP',channels={})
    for channel in ('1','2'):
        xorigin=origin+1e-9 if mismatched_origin and channel=='2' else origin
        metadata['channels'][channel]=dict(points=points,preamble=f'0,2,{points},1,{step},{xorigin},0,.034133,-48,128')
    path.with_suffix('.json').write_text(json.dumps(metadata))
    return path


def case(directory,identifier,shifts,*,kind='module',board='A',node=0):
    directory.mkdir(parents=True)
    (directory/'case.json').write_text(json.dumps(dict(id=identifier,label=identifier,board=board,observer_node=node,kind=kind)))
    for index,shift in enumerate(shifts):single(directory,index,shift)
    native=dict(CURRent=9.9e37,AVERages=0,DEViation=0,MINimum=0,MAXimum=0,CNT=20)
    (directory/'acquisition.json').write_text(json.dumps(dict(status='acquired',fresh_single_acquisitions=len(shifts),instrument_delay_s=native)))
    return directory


class ScopeReport(unittest.TestCase):
    def test_only_fresh_singles_count_and_invalid_native_current_does_not_poison_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=case(root/'a','A_M1',[2e-9,4e-9])
            extra=single(folder,99,80e-9)
            extra.rename(folder/'persistence_last_pair.npz');extra.with_suffix('.json').rename(folder/'persistence_last_pair.json')
            result=report.build_report(root,make_plots=False);item=result['cases'][0]
            self.assertTrue(result['complete']);self.assertEqual((item['valid_acquisition_count'],item['paired_edge_count']),(2,2))
            self.assertAlmostEqual(item['raw']['acquisition_mean_stats']['mean_s'],3e-9,delta=.1e-9)
            self.assertFalse(item['instrument_native']['current_valid']);self.assertTrue(item['instrument_native']['statistics_valid'])
            self.assertFalse(item['persistence_diagnostic']['official_statistics'])
            self.assertTrue((root/'summary.csv').is_file());self.assertTrue((folder/'analysis.json').is_file())

    def test_baselines_are_separate_constant_mean_corrections_without_variance_subtraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);case(root/'baseline','A_M1',[2e-9,4e-9]);case(root/'module','B_M6',[8e-9,10e-9],board='B',node=5)
            case(root/'instrument','A_same_sync',[1e-9,1e-9],kind='instrument_calibration',node=None)
            result=report.build_report(root,make_plots=False);module=next(x for x in result['cases'] if x['case']['id']=='B_M6')
            relative=module['corrections']['relative_to_A_M1'];instrument=module['corrections']['instrument_corrected']
            self.assertAlmostEqual(relative['mean_s'],6e-9,delta=.15e-9);self.assertAlmostEqual(instrument['mean_s'],8e-9,delta=.15e-9)
            self.assertEqual(relative['sample_sd_s'],module['raw']['acquisition_mean_stats']['sample_sd_s'])
            self.assertIn('GPIO/PCB',relative['meaning']);self.assertIn('bias removed',instrument['meaning'])
            self.assertTrue(relative['provisional'])
            self.assertEqual(relative['qualification'],'A_M1 path identity not physically verified')

    def test_origin_mismatch_and_adc_rail_hits_are_saved_without_crashing_other_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);case(root/'good','A_M1',[0,0]);bad=case(root/'bad','A_M3',[2e-9,2e-9],node=2)
            single(bad,1,2e-9,mismatched_origin=True);single(bad,2,2e-9,rail=True)
            result=report.build_report(root,make_plots=False);item=next(x for x in result['cases'] if x['case']['id']=='A_M3')
            self.assertFalse(result['complete']);self.assertEqual(result['status'],'partial')
            self.assertEqual((item['valid_acquisition_count'],item['invalid_acquisition_count']),(1,2))
            self.assertTrue(any('x_origin' in error for error in item['errors']))
            self.assertTrue(any('ADC rail' in error for error in item['errors']))

    def test_empty_or_persistence_only_cases_are_not_reported_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=case(root/'empty','A_M1',[])
            path=single(folder,0,0);path.rename(folder/'persistence_last_pair.npz');path.with_suffix('.json').rename(folder/'persistence_last_pair.json')
            result=report.build_report(root,make_plots=False)
            self.assertFalse(result['complete']);self.assertEqual(result['status'],'failed')
            self.assertTrue(result['cases'][0]['persistence_diagnostic']['pairing']['count'])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(report.build_report(tmp,make_plots=False)['complete'])

    def test_multiple_edges_do_not_inflate_independent_acquisition_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=case(root/'wide','A_M3',[0],node=2);single(folder,0,3e-9,wide=True)
            item=report.build_report(root,make_plots=False)['cases'][0]
            self.assertEqual((item['valid_acquisition_count'],item['paired_edge_count']),(1,5))
            self.assertIsNone(item['raw']['acquisition_mean_stats']['sample_sd_s'])
            self.assertTrue(item['acquisitions'][0]['period_verified'])

    def test_declared_fresh_acquisition_count_and_duplicate_identity_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=case(root/'a','A_M1',[0,0]);metadata=folder/'single_0001.json'
            value=json.loads(metadata.read_text());value['utc']=json.loads((folder/'single_0000.json').read_text())['utc'];metadata.write_text(json.dumps(value))
            item=report.build_report(root,make_plots=False)['cases'][0]
            self.assertFalse(item['complete']);self.assertEqual(item['invalid_acquisition_count'],1)
            acquisition=json.loads((folder/'acquisition.json').read_text());acquisition['fresh_single_acquisitions']=5;(folder/'acquisition.json').write_text(json.dumps(acquisition))
            item=report.build_report(root,make_plots=False)['cases'][0]
            self.assertTrue(any('declared 5' in x for x in item['errors']))

    def test_native_sentinel_nan_count_and_order_validation(self):
        good=dict(CURRent=0,AVERages=0,DEViation=1e-10,MINimum=-1e-9,MAXimum=1e-9,CNT=10)
        self.assertTrue(report.validate_native(good)['statistics_valid'])
        for changes in (dict(CNT=1),dict(AVERages=9.9e37),dict(DEViation=float('nan')),dict(AVERages=2e-9)):
            self.assertFalse(report.validate_native(dict(good,**changes))['statistics_valid'])

    def test_duplicate_case_labels_and_bad_field_values_are_individual_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);case(root/'a','A_M1',[0]);case(root/'b','A_M1',[0]);bad=case(root/'c','bad',[0])
            (bad/'case.json').write_text(json.dumps(dict(id='bad')))
            result=report.build_report(root,make_plots=False)
            self.assertFalse(result['complete']);self.assertTrue(all(x['status']=='failed' for x in result['cases']))
            self.assertTrue((bad/'analysis.json').is_file())

    def test_scientific_plot_is_a_real_png_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);case(root/'a','A_M1',[0,1e-9])
            result=report.build_report(root)
            self.assertTrue(result['complete'])
            png=(root/'delaytrace_histogram.png').read_bytes()
            self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'));self.assertGreater(len(png),10000)


if __name__=='__main__':unittest.main()
