"""Configure/sweep/collect three already loaded CT/RAG images; never programs FPGA/flash."""
from pathlib import Path
from decimal import Decimal
import argparse,datetime,hashlib,json,os,re,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from physical_codec import Config,MODES

def tq(path):
    value=Path(path).resolve().as_posix()
    if any(c in value for c in '{}\n\r'):raise ValueError('Unsupported Tcl path')
    return '{'+value+'}'

def render(targets,ltx,output,action,configs,timeout_ms=300000,post_calibration_ms=20):
    if len(set(targets))!=3 or any(not re.fullmatch(r'[A-Za-z0-9]+',t) for t in targets):raise ValueError('Three distinct alphanumeric cable serials required, in ring order')
    text='source '+tq(ROOT/'scripts/physical_hw.tcl')+'\nopen_hw_manager\nconnect_hw_server\n'
    text+='set physical_hw::targets {'+' '.join(targets)+'}\nset physical_hw::ltx '+tq(ltx)+'\n'
    text+=f'set physical_hw::timeout_ms {int(timeout_ms)}\n'
    for i,c in enumerate(configs):
        folder=output/(f'configuration_{i:03d}' if len(configs)>1 else 'pages')
        text+='file mkdir '+tq(folder)+'\nset physical_hw::output '+tq(folder)+'\n'
        if action in ('configure','run','sweep'):text+=f'physical_hw::configure {c.register():040x}\n'
        if action in ('run','sweep'):text+=f'physical_hw::run {c.repetitions} {post_calibration_ms}\n'
    if action=='start':text+='physical_hw::wait_idle\nphysical_hw::pulse [lindex $physical_hw::targets 0] 1\n'
    elif action=='stop':text+='physical_hw::pulse [lindex $physical_hw::targets 0] 2\nphysical_hw::collect\n'
    elif action=='collect':text+='physical_hw::collect\n'
    elif action=='status':text+='''set fault_found 0
foreach t $physical_hw::targets {
 set v [physical_hw::select $t]
 set s [expr 0x[obsidian_hw::read_input $v 0]]
 puts "PHYSICAL_STATUS $t [format %064llx $s]"
 puts "PHYSICAL_DIAG $t raw=[obsidian_hw::read_input $v 3] links=[obsidian_hw::read_input $v 4] aurora_errors=[obsidian_hw::read_input $v 5] lost=[obsidian_hw::read_input $v 7]"
 close_hw_target
 if {$s & (1<<12)} {set fault_found 1}
}
if {$fault_found} {error "Firmware fault; all board snapshots were printed above"}
'''
    elif action=='initialize':text+='physical_hw::initialize\n'
    return text+'close_hw_manager\nputs "PHYSICAL_COMMAND_COMPLETE"\n'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('initialize','configure','start','stop','status','run','sweep','collect'))
    p.add_argument('--targets',nargs=3,default=['OBS001A','OBS003A','OBS002A'])
    p.add_argument('--image-dir',type=Path,default=ROOT/'build/physical_runtime')
    p.add_argument('--config',type=Path,help='Configuration object; sweep accepts a JSON list of objects')
    p.add_argument('--mode',choices=('CT','RAG'),default='CT');p.add_argument('--payload-bytes',type=int,default=4096)
    p.add_argument('--local-bytes',type=int,default=6);p.add_argument('--generation',type=int,default=1)
    hops=p.add_mutually_exclusive_group();hops.add_argument('--hops',type=int);hops.add_argument('--target-modules',type=int)
    p.add_argument('--repetitions',type=int,default=128);p.add_argument('--period-us',type=Decimal,default=Decimal(100))
    p.add_argument('--output',type=Path,required=True);p.add_argument('--timeout-seconds',type=int,default=300)
    p.add_argument('--post-calibration-ms',type=int,default=20)
    p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    try:
        if a.timeout_seconds<1 or a.post_calibration_ms<0:raise ValueError('Invalid timeout/calibration interval')
        if a.config:
            data=json.loads(a.config.read_text(encoding='utf-8'));data=data if isinstance(data,list) else [data]
            configs=[Config.from_dict(c) for c in data]
        else:
            ticks=a.period_us/Decimal('.016')
            if ticks!=int(ticks):raise ValueError('Period must be an exact multiple of 16 ns')
            h=a.hops if a.hops is not None else (a.target_modules-1 if a.target_modules is not None else 2)
            configs=[Config(a.generation,a.payload_bytes,a.local_bytes,h,MODES[a.mode],a.repetitions,int(ticks)).validate()]
        if not configs or (a.action!='sweep' and len(configs)!=1):raise ValueError('Only sweep accepts multiple configurations')
        if len({c.generation for c in configs})!=len(configs):raise ValueError('Sweep generations must be unique')
        if a.output.exists() and any(a.output.iterdir()):raise ValueError('Use a new empty output directory')
        ltx=a.image_dir/'obsidian_benchmark.ltx';bit=a.image_dir/'obsidian_benchmark.bit'
        if not a.dry_run:
            execution=json.loads((a.image_dir/'execution.json').read_text())
            manifest=(a.image_dir/'build_manifest.txt').read_text()
            if execution.get('status')!='passed' or 'schema=physical_v3' not in manifest or 'status=implemented_timing_pass_bitstream_generated' not in manifest or not bit.is_file() or not ltx.is_file():
                raise ValueError('A newly accepted common physical_v3 BIT/LTX is required')
        script=render(a.targets,ltx,a.output,a.action,configs,a.timeout_seconds*1000,a.post_calibration_ms)
    except (ValueError,KeyError,OSError) as e:p.error(str(e))
    a.output.mkdir(parents=True,exist_ok=True);(a.output/'run.tcl').write_text(script,encoding='utf-8')
    metadata=dict(schema='physical_campaign_v3',source='dry_run' if a.dry_run else 'hardware_jtag',
        created_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),action=a.action,
        targets=dict(zip('ABC',a.targets)),configurations=[c.__dict__ for c in configs] if a.action in ('configure','run','sweep') else None,hardware_programmed=False,
        post_calibration_ms=a.post_calibration_ms,raw_counter_origins_reset=a.action=='initialize',bitstream_sha256=hashlib.sha256(bit.read_bytes()).hexdigest() if bit.is_file() else None)
    (a.output/'campaign.json').write_text(json.dumps(metadata,indent=2)+'\n')
    if a.dry_run:print(a.output/'run.tcl');return
    vivado=os.environ.get('VIVADO') or shutil.which('vivado') or shutil.which('vivado.bat') or 'C:/AMDDesignTools/2025.2/Vivado/bin/vivado.bat'
    env=os.environ.copy();env['PATH']=str(ROOT/'scripts/windows_compat')+os.pathsep+env.get('PATH','')
    with (a.output/'hardware.log').open('w') as log:
        result=subprocess.run([vivado,'-mode','batch','-nojournal','-nolog','-source',str((a.output/'run.tcl').resolve())],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    transcript=(a.output/'hardware.log').read_text(errors='replace')
    if result.returncode or 'PHYSICAL_COMMAND_COMPLETE' not in transcript or re.search(r'^ERROR:',transcript,re.M):raise RuntimeError('JTAG action failed; inspect hardware.log')
    from decode_physical import read_page,decode_page,calibrated_metrics,FIELDS
    import csv
    rows=[];events=[];sync=[];page_info=[]
    for path in sorted(a.output.rglob('*_page_*.json')):
        page=read_page(path);r,e,c=decode_page(page);rows+=r;events+=e;sync+=c
        page_info.append({k:page[k] for k in ('board','page','summary_count','event_count','calibration_count','lost_events','lost_calibration')})
    with (a.output/'results.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction='ignore');w.writeheader();w.writerows(rows)
    (a.output/'events.json').write_text(json.dumps(events,indent=2)+'\n');(a.output/'sync.json').write_text(json.dumps(sync,indent=2)+'\n')
    metadata.update(completed=True,summary_rows=len(rows),invalid_rows=sum(not r['valid'] for r in rows),pages=page_info)
    (a.output/'campaign.json').write_text(json.dumps(metadata,indent=2)+'\n')
    if metadata['invalid_rows']:
        raise RuntimeError('Hardware campaign contains invalid trials; results and raw pages have been preserved')
if __name__=='__main__':main()
