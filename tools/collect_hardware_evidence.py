"""Preserve and verify completed hardware captures without contacting the boards."""
from pathlib import Path
import argparse, csv, datetime, hashlib, json, shutil, sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from verify_physical_capture import verify
from decode_physical import read_page, decode_page, FIELDS
from analyze_physical import plot, identify


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture',type=Path,action='append',required=True)
    p.add_argument('--programming',type=Path,required=True)
    p.add_argument('--ila',type=Path)
    p.add_argument('--host-tests',type=Path,required=True)
    p.add_argument('--output',type=Path,default=ROOT/'build/report_outputs/hardware_validation')
    a=p.parse_args()
    a.output=a.output.resolve()
    if a.output.exists() and any(a.output.iterdir()):raise ValueError('Use an empty evidence directory')
    programming=json.loads((a.programming/'programming.json').read_text())
    if programming.get('status')!='passed':raise ValueError('Successful explicit programming/initialization evidence required')
    host=json.loads(a.host_tests.read_text())
    if host.get('status')!='passed':raise ValueError('Passing current host tests required')
    a.output.mkdir(parents=True,exist_ok=True)
    all_rows=[];all_events=[];all_sync=[];sets=[];image=None;trials=set();pauses=[]
    for folder in a.capture:
        destination=a.output/folder.name
        shutil.copytree(folder,destination)
        result=verify(destination)
        if not result['passed']:raise ValueError('Failed hardware invariants: '+str(result['errors']))
        image=image or result['bitstream_sha256']
        if result['bitstream_sha256']!=image:raise ValueError('Different FPGA images in capture sets')
        (destination/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
        pauses.extend(dict(capture_set=folder.name,**entry) for entry in result['collection_pauses'])
        sets.append(dict(name=folder.name,summary_rows=result['summary_rows'],configurations=result['configurations']))
        for path in sorted(destination.rglob('*_page_*.json')):
            page=read_page(path);rows,events,sync=decode_page(page)
            for row in rows:
                row['capture_set']=folder.name
                trials.add((folder.name,row['generation'],row['run'],row['trial']))
            all_rows+=rows;all_events+=events;all_sync+=sync
    expected=programming['artifact_sha256']['obsidian_benchmark.bit']
    if image!=expected:raise ValueError('Programmed image and captures disagree')
    shutil.copytree(a.programming,a.output/'programming')
    if a.ila:
        ila_result=json.loads((a.ila/'verification.json').read_text())
        if not ila_result.get('passed') or ila_result.get('source')!='hardware_jtag':raise ValueError('Passing real ILA verification required')
        shutil.copytree(a.ila,a.output/'ila')
    shutil.copy2(a.host_tests,a.output/'host_tests.json')
    test_log=a.host_tests.with_suffix('.log')
    if test_log.exists():shutil.copy2(test_log,a.output/'host_tests.log')
    with (a.output/'results.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['capture_set',*FIELDS],extrasaction='ignore');w.writeheader();w.writerows(all_rows)
    (a.output/'events.json').write_text(json.dumps(all_events,indent=2)+'\n')
    (a.output/'sync.json').write_text(json.dumps(all_sync,indent=2)+'\n')
    with (a.output/'collection_pauses.csv').open('w',newline='',encoding='utf-8') as f:
        fields=['capture_set','board','generation','run','from_page','to_page','page_seal_raw','next_launch_raw','ticks','duration_us','scope']
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(pauses)
    plot(all_rows,a.output/'durations.png')
    (a.output/'model.json').write_text(json.dumps(identify(all_rows,all_events,None),indent=2)+'\n')
    hashes={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(a.output.rglob('*')) if path.is_file()}
    report=dict(schema='physical_hardware_suite_v1',status='passed',source='hardware_jtag',
                recorded_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                physical_boards=3,bitstream_sha256=image,physical_trials=len(trials),summary_rows=len(all_rows),
                invalid_rows=sum(not row['valid'] for row in all_rows),capture_sets=sets,host_tests=host,collection_pauses=pauses,
                input_sha256=hashes,interboard_calibration='absent; remote durations/skews unavailable',
                caveat='Trace and calibration saturation are recorded per page; no exhaustive trace claimed at high H.')
    (a.output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('input_sha256','capture_sets')},indent=2))


if __name__=='__main__':main()
