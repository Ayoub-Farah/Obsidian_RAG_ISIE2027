"""Contract tests, synthetic scope fixtures. No hardware observations."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'scripts')]
from ptp_config import normalize,partition,locate,logical_step,registers,config_id
from run_ptp_campaign import render
from analyze_ptp import metrics,scope_rows,summarize


class PtpContract(unittest.TestCase):
    def test_single_node_defaults_and_example(self):
        import json
        cfg=normalize({})
        self.assertEqual((cfg['capacity'],cfg['nodes']),(1,3))
        example=normalize(json.loads((ROOT/'config/ptp_emulation_3.example.json').read_text()))
        self.assertEqual((example['capacity'],example['nodes']),(1,3))
        for node,board in ((1,'A'),(2,'B'),(3,'C')):
            selected=locate(cfg,node)
            self.assertEqual((selected['board'],selected['local_index']),(board,0))
            self.assertEqual(len(registers(cfg,selected['board_index'])),20)
        with self.assertRaises(ValueError):normalize(dict(nodes=4))

    def test_population_and_every_observable_id(self):
        for n in (3,6,10,20,30,40,50,60):
            cfg=normalize(dict(nodes=n,capacity=20))
            self.assertEqual(sum(c for _,c in partition(n)),n)
            for module in range(1,n+1):
                d=locate(cfg,module);first,count=partition(n)[d['board_index']]
                self.assertEqual(d['node_id'],first+d['local_index'])
                self.assertLess(d['local_index'],count)
            with self.assertRaises(ValueError):locate(cfg,n+1)
        self.assertEqual(partition(10),[(0,4),(4,3),(7,3)])

    def test_signed_drift_and_link_register_planes(self):
        self.assertEqual(logical_step(2000),(1<<32)+8589)
        self.assertEqual(logical_step(-2000),(1<<32)-8589)
        cfg=normalize(dict(nodes=3,links=[dict(forward_ticks=10,reverse_ticks=20),dict(forward_ticks=30,reverse_ticks=40)]))
        self.assertEqual(registers(cfg,0)[18],1|(20<<16))
        self.assertEqual(registers(cfg,1)[18],10|(40<<16))
        self.assertEqual(registers(cfg,2)[18],30|(1<<16))
        self.assertEqual(registers(cfg,0)[4],registers(cfg,2)[4])

    def test_bounds_and_hash(self):
        for data in (dict(nodes=True),dict(nodes=61),dict(capacity=12,nodes=60),dict(nodes=3,drift_ppb=[1]),dict(jitter_mask=2),dict(period_ticks=0),dict(surprise=1)):
            with self.subTest(data=data),self.assertRaises(ValueError):normalize(data)
        self.assertEqual(normalize(dict(nodes=180,capacity=60),simulation=True)['nodes'],180)
        self.assertNotEqual(config_id(normalize({})),config_id(normalize(dict(seed=42))))

    def test_observe_is_independent_and_no_programming(self):
        cfg=normalize(dict(nodes=60,capacity=20))
        for node,serial,index in ((60,'C3',59),(40,'B2',39)):
            t=render('observe',cfg,['A1','B2','C3'],Path('image'),Path('out'),node)
            self.assertIn(f'ptp_hw::observe {serial} {index}',t)
            for forbidden in ('stop_all','ptp_hw::stage','program_hw',' 4\n',' 5\n'):
                self.assertNotIn(forbidden,t)

    def test_config_commits_followers_before_anchor_and_start_last(self):
        t=render('run',normalize({}),['A1','B2','C3'],Path('image'),Path('out'))
        self.assertLess(t.index('stage C3'),t.index('pulse B2 4'))
        self.assertLess(t.index('pulse B2 4'),t.index('pulse A1 4'))
        self.assertLess(t.index('check_active'),t.index('pulse A1 5'))

    def test_signed_scope_metrics_and_epoch_gaps(self):
        rows=scope_rows([dict(node_id=1,epoch_index=n,reference_ns=n*100000,observed_ns=n*100000+d) for n,d in ((0,30),(1,34),(3,32))],2)
        summary=summarize(rows,'calibrated_delta_ns')['1']
        self.assertEqual(summary['mean_ns'],30)
        self.assertEqual(summary['raw']['mean_ns'],32)
        self.assertEqual(summary['missing_epochs_between_samples'],1)
        self.assertGreater(summary['rms_ns'],summary['sigma_ns'])
        with self.assertRaises(ValueError):scope_rows([dict(node_id=1,epoch_index=0,reference_ns=0,observed_ns=1)]*2,0)
        self.assertEqual(metrics([-30,-10])['mean_ns'],-20)


if __name__=='__main__':unittest.main()
