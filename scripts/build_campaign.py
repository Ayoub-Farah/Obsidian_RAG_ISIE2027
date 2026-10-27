#!/usr/bin/env python3
"""Build one benchmark profile for each of three Obsidian cards."""
from pathlib import Path
import argparse,json,subprocess,sys,os

def commands(root,mode,nodes,data_bytes=6,ref_bytes=2,run_cycles=128,partitions=None,project_only=False):
    if nodes<3:raise ValueError('A three-card campaign requires N >= 3')
    if min(data_bytes,ref_bytes)<1 or run_cycles<0:raise ValueError('Invalid payload or campaign duration')
    if partitions is None:
        quotient,remainder=divmod(nodes,3)
        partitions=[quotient+(i<remainder) for i in range(3)]
    if len(partitions)!=3 or min(partitions)<1 or sum(partitions)!=nodes:
        raise ValueError('Three positive partitions must sum to N')
    result=[];base=0
    for count in partitions:
        result.append([sys.executable,str(root/'scripts'/'vivado.py'),
                       'project' if project_only else 'build',
                       *map(str,[mode,nodes,base,count,data_bytes,ref_bytes,run_cycles])])
        base+=count
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',type=int,choices=range(5),required=True)
    p.add_argument('--nodes',type=int,default=3);p.add_argument('--data-bytes',type=int,default=6)
    p.add_argument('--ref-bytes',type=int,default=2);p.add_argument('--run-cycles',type=int,default=128)
    p.add_argument('--partitions',type=int,nargs=3);p.add_argument('--project-only',action='store_true')
    p.add_argument('--runtime-config',action='store_true',help='Build a runtime-configurable capacity, up to 30 nodes')
    p.add_argument('--synth-only',action='store_true')
    p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    try:cmds=commands(root,a.mode,a.nodes,a.data_bytes,a.ref_bytes,a.run_cycles,a.partitions,a.project_only)
    except ValueError as e:p.error(str(e))
    if a.runtime_config:
        if a.nodes>30 or a.nodes%3 or a.partitions is not None:
            p.error('Runtime capacity must be a multiple of 3, at most 30; balanced capacity required')
        os.environ['OBSIDIAN_RUNTIME_CONFIG']='1'
        cmds=cmds[:1]  # Runtime IDs make the same image usable on all three cards.
    if a.synth_only:os.environ['OBSIDIAN_SYNTH_ONLY']='1'
    if a.dry_run:print(json.dumps(cmds,indent=2));return
    for cmd in cmds:
        print(' '.join(cmd),flush=True)
        subprocess.run(cmd,cwd=root,check=True)
if __name__=='__main__':main()
