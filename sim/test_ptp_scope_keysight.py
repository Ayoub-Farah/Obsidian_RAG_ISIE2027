"""Keysight voltage scaling and real CH1/CH3 artifact decoding; no hardware I/O."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from ptp_scope_analysis import decode_preamble,decode_waveform
from ptp_scope_report import build_report


class KeysightWaveforms(unittest.TestCase):
    def test_origin_is_volts_and_reference_is_adc_codes(self):
        preamble=decode_preamble('0,0,4,1,2e-10,-1e-9,0,.01,1.5,128')
        t,v=decode_waveform(bytes((0,100,128,255)),preamble,voltage_encoding='keysight_byte')
        np.testing.assert_allclose(v,(.22,1.22,1.5,2.77),atol=1e-15)
        np.testing.assert_allclose(t,(-1e-9,-.8e-9,-.6e-9,-.4e-9),atol=1e-24)
        with self.assertRaises(ValueError):
            decode_waveform(b'abcd',preamble,voltage_encoding='unknown_scope')

    def test_actual_ch1_ch3_files_preserve_signed_delay_and_instrument_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for identifier,kind,delays in [('A_same_sync','instrument_calibration',[.7e-9,.7e-9]),
                                           ('A_M2','module',[7.3e-9,-5.2e-9])]:
                folder=root/identifier;folder.mkdir()
                (folder/'case.json').write_text(json.dumps(dict(id=identifier,label=identifier,kind=kind,
                    board='A',observer_node=None if kind=='instrument_calibration' else 1)))
                for index,delay in enumerate(delays):
                    t=np.arange(4000)*.5e-9-1e-6
                    arrays={}
                    metadata=dict(utc=f'2026-10-30T16:00:{index:02d}Z',trigger_state='STOP',
                                  reference_channel=1,observed_channel=3,allow_per_channel_x_origin=True,channels={})
                    for channel,shift in [(1,0),(3,delay)]:
                        xorigin=-1e-6+(.14e-9 if channel==3 else 0)
                        local_t=np.arange(4000)*.5e-9+xorigin
                        v=3.3*np.clip((local_t-shift)/8e-9,0,1)
                        arrays[f'ch{channel}']=np.rint((v-1.6)/.025+128).astype(np.uint8)
                        metadata['channels'][str(channel)]=dict(points=4000,voltage_encoding='keysight_byte',
                            preamble=f'0,0,4000,1,5e-10,{xorigin},0,.025,1.6,128')
                    np.savez_compressed(folder/f'single_{index:04d}.npz',**arrays)
                    (folder/f'single_{index:04d}.json').write_text(json.dumps(metadata))
                (folder/'acquisition.json').write_text(json.dumps(dict(status='acquired',fresh_single_acquisitions=2)))
            result=build_report(root,threshold_v=1.65,make_plots=False)
            self.assertTrue(result['complete'])
            module=next(case for case in result['cases'] if case['case']['id']=='A_M2')
            self.assertEqual(module['valid_acquisition_count'],2)
            np.testing.assert_allclose([row['delay_s'] for row in module['paired_samples']],
                                       [7.3e-9,-5.2e-9],atol=.1e-9)
            corrected=module['corrections']['instrument_corrected']
            self.assertTrue(corrected['available'])
            self.assertAlmostEqual(corrected['mean_s'],.35e-9,delta=.15e-9)


if __name__=='__main__':
    unittest.main()
