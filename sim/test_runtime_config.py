"""Runtime host configuration and journal format boundary tests."""
import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
def module(name,file):
 spec=importlib.util.spec_from_file_location(name,ROOT/file)
 value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
runtime=module('runtime_campaign','scripts/run_runtime_campaign.py')
decoder=module('runtime_decoder','scripts/decode_log.py')
class RuntimeConfigTests(unittest.TestCase):
 def test_all_populations_cover_contiguous_ring(self):
  for capacity in range(3,31,3):
   for n in range(3,capacity+1):
    counts=runtime.partitions(n,capacity);base=0
    for local in counts:
     self.assertLessEqual(local,capacity//3)
     for mode in (0,2):
      word=runtime.config_word(mode,n,base,local)
      self.assertEqual((word&3,(word>>2)&63,(word>>8)&63,(word>>14)&63),(mode,n,base,local))
     base+=local
    self.assertEqual(base,n)
 def test_reject_out_of_capacity(self):
  for n,c in [(2,30),(31,30),(7,6),(3,4)]:
   with self.assertRaises(ValueError):runtime.partitions(n,c)
  for args in [(1,3,0,1),(2,3,2,2),(2,30,0,11)]:
   with self.assertRaises(ValueError):runtime.config_word(*args)
 def test_return_format_preserves_legacy_measurement(self):
  for version in (0,256):
   value=(1<<448)|(2<<416)|(3<<400)|(1<<384)|(10<<96)|(30<<160)|(20<<224)|((16|version)<<320)
   rows,unused=decoder.decode_dump({'board_id':'A','raw_records_hex':[f'{value:0128x}']})
   row=rows[0];self.assertEqual(row['status'],'ok')
   self.assertEqual(row['T_return_us'],'0.32' if version else '')
   self.assertEqual(row['first_tx_delay_ns'],'' if version else '320')
if __name__=='__main__':unittest.main()
