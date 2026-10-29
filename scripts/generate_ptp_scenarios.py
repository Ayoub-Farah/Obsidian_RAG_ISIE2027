"""Create deterministic PTP campaign configurations; never contacts hardware."""
from pathlib import Path
import argparse
import json
import random
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from ptp_config import normalize


def scenarios(nodes,capacity,seed,simulation=False):
    base=dict(nodes=nodes,capacity=capacity,seed=seed)
    rng=random.Random(seed)
    cases=[('symmetric',{}),
           ('symmetric_delay',dict(links=[dict(forward_ticks=100,reverse_ticks=100) for _ in range(nodes-1)])),
           ('drift_alternating',dict(drift_ppb=[2000 if i%2 else -2000 for i in range(nodes)])),
           ('drift_distribution',dict(drift_ppb=[rng.randint(-2000,2000) for _ in range(nodes)])),
           ('asymmetry_coherent',dict(links=[dict(forward_ticks=5,reverse_ticks=1) for _ in range(nodes-1)])),
           ('asymmetry_alternating',dict(links=[dict(forward_ticks=5 if i%2 else 1,reverse_ticks=1 if i%2 else 5) for i in range(nodes-1)])),
           ('jitter',dict(jitter_mask=3)),('missing_frames',dict(drop_every=100)),
           ('combined',dict(jitter_mask=3,drop_every=100,drift_ppb=[rng.randint(-2000,2000) for _ in range(nodes)]))]
    cases += [(f'maintenance_ratio_{ratio}',dict(maintenance_ratio=ratio,drift_ppb=[2000 if i%2 else -2000 for i in range(nodes)])) for ratio in (1,5,20,100)]
    return [(name,normalize(dict(base,run_id=i+1,**values),simulation=simulation)) for i,(name,values) in enumerate(cases)]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--nodes',type=int,default=3);p.add_argument('--capacity',type=int,default=1)
    p.add_argument('--seed',type=int,default=12345);p.add_argument('--simulation',action='store_true')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists() and any(a.output.iterdir()):p.error('Use an empty output directory')
    try:cases=scenarios(a.nodes,a.capacity,a.seed,a.simulation)
    except ValueError as e:p.error(str(e))
    a.output.mkdir(parents=True,exist_ok=True)
    for name,cfg in cases:(a.output/(name+'.json')).write_text(json.dumps(cfg,indent=2)+'\n')
    print(f'{len(cases)} reproducible configurations written to {a.output}; no campaigns executed')


if __name__=='__main__':main()
