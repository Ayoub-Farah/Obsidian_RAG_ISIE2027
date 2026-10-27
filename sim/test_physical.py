"""Synthetic unit fixtures; none of these values are hardware observations."""
from pathlib import Path
import json,sys,tempfile,unittest,zlib
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'scripts')]
from physical_codec import Config,encode,inspect,relay
from frame_codec import FrameError,pattern
from decode_physical import read_page,decode_page,calibrated_metrics,map_stamp
from analyze_physical import calibrate,identify
from run_physical_campaign import render

class RuntimeContract(unittest.TestCase):
    def test_register_limits_and_roundtrip(self):
        for c in [Config(),Config(0xffffffff,4096,1365,65535,1,0xffffffff,0xffffffff),Config(payload_bytes=1,mode=2)]:
            self.assertEqual(Config.from_register(c.register()),c)
        for kwargs in [dict(payload_bytes=0),dict(payload_bytes=4097),dict(local_bytes=1366),dict(payload_bytes=2,local_bytes=1),dict(hops=0),dict(hops=65536),dict(period_ticks=0),dict(repetitions=-1),dict(mode=0),dict(mode=True)]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):Config(**kwargs).register()
        self.assertEqual(Config.from_dict(dict(mode='RAG',target_modules=65536)).hops,65535)
        with self.assertRaises(ValueError):Config.from_dict(dict(target_modules=3,hops=3))

    def test_ct_slots_constant_length_and_integrity(self):
        for p,s in [(3,1),(257,7),(4095,1365),(4096,1365)]:
            c=Config(payload_bytes=p,local_bytes=s);initial=encode(c,3,7,0)
            b,_=relay(initial,c,1);cc,_=relay(b,c,2);retired,info=relay(cc,c,0)
            self.assertIsNone(retired);self.assertTrue(info['crc_valid']);self.assertEqual(len(cc),len(initial))
            self.assertEqual(cc[32:32+3*s],b''.join(pattern(i,7,s) for i in range(3)))
            self.assertEqual(cc[32+3*s:-4],initial[32+3*s:-4])
            self.assertEqual(b[32:32+s],initial[32:32+s]);self.assertEqual(b[32+2*s:-4],initial[32+2*s:-4])

    def test_overwritten_corruption_is_not_healed(self):
        c=Config(payload_bytes=257,local_bytes=7)
        for position in [32+7,32+14,200,289,292]:
            raw=bytearray(encode(c,1,4,0));raw[position]^=1
            b,info=relay(bytes(raw),c,1);self.assertFalse(info['crc_valid'])
            cc,info=relay(b,c,2);self.assertFalse(info['crc_valid'])
            _,info=relay(cc,c,0);self.assertFalse(info['crc_valid'])
        bad=bytearray(encode(c,1,1,0));bad[20]^=1
        with self.assertRaises(FrameError):relay(bytes(bad),c,1)

    def test_physical_hops_include_repeated_origin_returns(self):
        for h in [1,2,3,4,29,65535]:
            c=Config(payload_bytes=1,local_bytes=1,hops=h,mode=2)
            raw=encode(c,1,8,2)
            for hop in range(1,h+1):
                raw,info=relay(raw,c,(2+hop)%3)
                self.assertEqual(raw is None,hop==h)
            self.assertTrue(info['crc_valid']);self.assertEqual(info['hop']+1,h)

    def test_host_never_programs_and_handles_sweep(self):
        text=render(['OBS001A','OBS003A','OBS002A'],ROOT/'unused.ltx',ROOT/'unused', 'sweep',[Config(),Config(generation=2,mode=2)])
        self.assertNotIn('program_hw_devices',text);self.assertNotIn('reset',text)
        self.assertEqual(text.count('physical_hw::configure '),2)
        with self.assertRaises(ValueError):render(['A','A','C'],ROOT/'x',ROOT/'x','run',[Config()])

class MeasurementContract(unittest.TestCase):
    def page(self):
        c=Config(payload_bytes=64,local_bytes=6,repetitions=1)
        s=c.register()|1<<160|1<<192|1<<256|100<<336|149<<400|951<<464|1000<<528|900<<1664
        w=[0]*8192
        for j in range(32):w[j]=s>>(64*j)&((1<<64)-1)
        w[7168]=0x5048595300030001;w[7169]=1<<32
        for j in range(5):w[7172+j]=c.register()>>(32*j)&0xffffffff
        return dict(schema='physical_v3',source='unit_test_synthetic',board='A',words=[f'{v:016x}' for v in w])

    def test_local_rtt_and_invalid_remote_calibration(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'page.json';path.write_text(json.dumps(self.page()))
            rows,_,_=decode_page(read_page(path));r=rows[0]
        self.assertEqual(r['ct_rtt_ticks'],900);self.assertEqual(r['ct_rtt_us'],14.4)
        # No local injection is an unavailable wait, never a measured zero.
        page=self.page();words=[int(w,16) for w in page['words']];s=sum(words[j]<<(64*j) for j in range(32))
        s|=((1<<128)-1)<<336
        for j in range(32):words[j]=s>>(64*j)&((1<<64)-1)
        row,_,_=decode_page(dict(board='B',page=0,words=words,summary_count=1,event_count=0,calibration_count=0))
        self.assertIsNone(row[0]['launch_wait_us'])
        calibrated_metrics(rows,None);self.assertNotIn('launch_skew_ns',r)
        assumed=dict(status='uncalibrated_symmetry_assumption',calibration_id='test',mappings=[dict(board='A',raw_ref=0,master_ref_ticks=0,slope=1,valid_from_raw=0,valid_to_raw=10000,uncertainty_ns=1)])
        self.assertIsNone(map_stamp(assumed,'A',100))
        assumed['status']='calibrated';self.assertIsNotNone(map_stamp(assumed,'A',100));self.assertIsNone(map_stamp(assumed,'A',10001))
        assumed['mappings'][0]['uncertainty_ns']=None;self.assertIsNone(map_stamp(assumed,'A',100))

    def test_corrupt_page_and_rtt_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'page.json';page=self.page();page['board']='B';path.write_text(json.dumps(page))
            with self.assertRaises(ValueError):read_page(path)
            page=self.page();v=int(page['words'][26],16);page['words'][26]=f'{v^1:016x}';path.write_text(json.dumps(page))
            with self.assertRaises(ValueError):decode_page(read_page(path))

    def exchanges(self):
        events=[]
        def clock(board,t):return {'A':int(t+100),'B':round((t+100000)/1.000002),'C':round((t+200000)/.999998)}[board]
        for parent,child in [('A','B'),('B','C')]:
            for seq in range(1,13):
                t=seq*10000+(1000 if parent=='B' else 0)
                for board,peer,kind,tx,time in [(parent,child,0x10,True,t),(child,parent,0x10,False,t+50),(child,parent,0x12,True,t+80),(parent,child,0x12,False,t+130),(child,parent,0x15,False,t+200)]:
                    events.append(dict(board=board,peer='ABC'.index(peer),sequence=seq,kind=kind,tx=tx,raw=clock(board,time),collision=False))
        return events

    def test_calibration_needs_external_asymmetry_and_brackets_data(self):
        events=self.exchanges();uncal=calibrate(events)
        self.assertEqual(uncal['status'],'uncalibrated_symmetry_assumption')
        measured=dict(status='measured',provenance='unit_test_synthetic',links={p:dict(forward_minus_reverse_ns=0.,uncertainty_ns=2.) for p in ('AB','BC')})
        result=calibrate(events,measured);self.assertEqual(result['status'],'calibrated')
        self.assertAlmostEqual(result['mappings'][1]['slope'],1.000002,places=5)
        self.assertGreater(result['mappings'][2]['uncertainty_ns'],16)
        with self.assertRaises(ValueError):calibrate(events[:10],measured)

    def test_empty_model_does_not_fabricate_parameters(self):
        model=identify([],[],None)
        self.assertIsNone(model['serialization_fit']);self.assertEqual(model['effective_link_delay_ns'],{})

if __name__=='__main__':unittest.main()
