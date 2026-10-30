"""Distance qualification arithmetic and complete-campaign gate, no instruments."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tools')]
import report_ptp_scope_distance as report
from ptp_config import normalize,config_id


class DistanceQualification(unittest.TestCase):
    def fixture(self,path,nodes=9):
        config=ROOT/'config/ptp_emulation_9_uniform_4ppm.json'
        cfg=normalize(json.loads(config.read_text()))
        health=dict(status='ok',cards=[dict(available=True,nominal=True,config_id_hex=f'{config_id(cfg):016x}') for _ in range(3)])
        (path/'health.json').write_text(json.dumps(health))
        cases=[]
        for node in range(nodes):
            cases.append(dict(case=dict(id=f'{"ABC"[node//3]}_M{node+1}',board='ABC'[node//3],kind='module',
                observer_node=node,wiring_verified=True,health_before_receipt='health.json',health_after_receipt='health.json'),
                complete=True,acquisition_count=2,invalid_acquisition_count=0,
                acquisitions=[dict(status='passed',signed_mean_s=value,utc=f'2026-10-30T16:00:0{i}Z')
                              for i,value in enumerate((0.,50e-9))]))
        return config,dict(cases=cases,complete=True,calibrations=dict(A_same_sync=dict(available=True,mean_s=5e-9)))

    def test_bias_subtraction_rms_and_directed_hop_decomposition(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);config,base=self.fixture(path)
            with patch.object(report,'build_report',return_value=base),patch.object(report,'plot'):
                result=report.qualify(path,config,minimum_count=2)
            self.assertTrue(result['campaign_complete'])
            row=result['modules'][3]
            self.assertEqual((row['module'],row['hops'],row['physical_crossings'],row['internal_hops']),('M4',3,1,2))
            self.assertAlmostEqual(row['corrected_mean_ns'],20)
            self.assertAlmostEqual(row['corrected_rms_ns'],(1025)**.5)
            self.assertAlmostEqual(row['sample_sd_ns'],50/(2**.5))
            self.assertAlmostEqual(row['corrected_max_abs_ns'],45)
            self.assertEqual(row['fraction_abs_over_20ns'],.5)
            self.assertEqual(row['fraction_abs_over_50ns'],0)
            self.assertTrue((path/'distance_measurements.csv').is_file())

    def test_discovered_cases_complete_does_not_mean_all_modules_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);config,base=self.fixture(path,nodes=8)
            with patch.object(report,'build_report',return_value=base),patch.object(report,'plot'):
                result=report.qualify(path,config,minimum_count=2)
            self.assertFalse(result['campaign_complete'])
            self.assertEqual(result['missing_modules'],['M9'])

    def test_health_configuration_mismatch_prevents_qualification(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);config,base=self.fixture(path)
            health=json.loads((path/'health.json').read_text());health['cards'][2]['config_id_hex']='0000000000000000'
            (path/'health.json').write_text(json.dumps(health))
            with patch.object(report,'build_report',return_value=base),patch.object(report,'plot'):
                result=report.qualify(path,config,minimum_count=2)
            self.assertFalse(result['campaign_complete'])
            self.assertFalse(result['modules'][0]['health_verified'])

    def test_all_data_can_be_complete_while_nominal_lock_check_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);config,base=self.fixture(path)
            health=json.loads((path/'health.json').read_text());health['status']='error';health['cards'][1]['nominal']=False
            (path/'health.json').write_text(json.dumps(health))
            with patch.object(report,'build_report',return_value=base),patch.object(report,'plot'):
                result=report.qualify(path,config,minimum_count=2)
            self.assertTrue(result['campaign_complete'])
            self.assertFalse(result['nominal_checks_passed'])
            self.assertEqual(result['status'],'complete_with_health_events')
            self.assertEqual(len(result['health_events']),18)

    def test_waived_calibration_reports_raw_values_without_inventing_a_bias(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);config,base=self.fixture(path)
            base['calibrations']['A_same_sync']=dict(available=False,mean_s=None)
            with patch.object(report,'build_report',return_value=base),patch.object(report,'plot'):
                strict=report.qualify(path,config,minimum_count=2)
                result=report.qualify(path,config,minimum_count=2,allow_uncalibrated=True)
            self.assertFalse(strict['campaign_complete'])
            self.assertTrue(result['campaign_complete'])
            self.assertEqual(result['timing_basis'],'raw_uncalibrated')
            row=result['modules'][0]
            self.assertIsNone(row['corrected_mean_ns'])
            self.assertAlmostEqual(row['measured_mean_ns'],25)
            self.assertAlmostEqual(row['measured_max_abs_ns'],50)


if __name__=='__main__':unittest.main()
