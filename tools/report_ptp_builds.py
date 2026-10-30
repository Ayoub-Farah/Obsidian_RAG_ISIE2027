"""Summarize only actually executed PTP build attempts and available reports."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil

ROOT=Path(__file__).resolve().parents[1]


def utilization(path):
    if not path.exists():return None
    for line in path.read_text(errors='replace').splitlines():
        cells=[v.strip() for v in line.split('|')[1:-1]]
        if cells and cells[0]=='obsidian_ptp_top':
            values=list(map(int,cells[2:]))
            return dict(luts=values[0],logic_luts=values[1],lutram=values[2],srl=values[3],
                        flip_flops=values[4],ramb36=values[5],ramb18=values[6],dsp=values[7])
    return None


def timing(path):
    if not path.exists():return None
    lines=path.read_text(errors='replace').splitlines()
    for i,line in enumerate(lines):
        if 'WNS(ns)' in line and 'WHS(ns)' in line:
            for candidate in lines[i+1:i+5]:
                values=candidate.split()
                if len(values)==12 and re.fullmatch(r'-?\d+\.\d+',values[0]):
                    return dict(setup_wns_ns=float(values[0]),hold_whs_ns=float(values[4]),pulse_width_wpws_ns=float(values[8]))
    return None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'build/report_outputs/ptp_builds')
    p.add_argument('--build',type=Path,action='append',default=[],help='Limit the report to these build directories')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);records=[]
    executions=[folder/'execution.json' for folder in a.build] if a.build else (ROOT/'build').rglob('execution.json')
    for execution in sorted(executions):
        execution=execution.resolve()
        folder=execution.parent;record=json.loads(execution.read_text())
        if record.get('schema')!='ptp_emulation_v1' or 'capacity' not in record:continue
        record['build_directory']=str(folder.relative_to(ROOT))
        record['synthesis_utilization']=utilization(folder/'synthesis_utilization.rpt')
        record['implementation_utilization']=utilization(folder/'implementation_utilization.rpt')
        record['routed_timing']=timing(folder/'timing_summary.rpt')
        source_file=folder/'source_sha256.json'
        if source_file.exists():
            hashes=json.loads(source_file.read_text())
            record['current_sources_match']=all((ROOT/n).exists() and hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h for n,h in hashes.items())
        dest=a.output/folder.relative_to(ROOT/'build');dest.mkdir(parents=True,exist_ok=True)
        for name in ('execution.json','source_sha256.json','build_manifest.txt','build.log',
                     'synthesis_utilization.rpt','synthesis_cdc.rpt','implementation_utilization.rpt',
                     'timing_summary.rpt','timing_checks.rpt','bus_skew.rpt','cdc.rpt','drc.rpt',
                     'gpio_test_ref_m1_o.rpt','gpio_test_obs_o.rpt'):
            if (folder/name).exists():shutil.copy2(folder/name,dest/name)
        records.append(record)
    report=dict(schema='ptp_build_attempts_v1',attempts=records,hardware_programmed=False,
                selected_validated_capacity=None,
                note='A synthesis result alone does not establish routed capacity or an operational margin.')
    (a.output/'attempts.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps([{k:r[k] for k in ('capacity','status','build_directory','synthesis_utilization','routed_timing')} for r in records],indent=2))


if __name__=='__main__':main()
