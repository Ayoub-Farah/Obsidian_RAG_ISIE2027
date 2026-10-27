"""Build the common CT/RAG image. Never connects to or programs hardware."""
from pathlib import Path
import argparse, datetime, hashlib, json, os, shutil, subprocess, sys
ROOT = Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-only',action='store_true')
    p.add_argument('--synth-only',action='store_true')
    p.add_argument('--reuse-ip',action='store_true',help='Reopen the existing common project and reuse unchanged generated IP')
    p.add_argument('--from-synth',action='store_true',help='Resume implementation only after verifying unchanged RTL/XDC and the saved checkpoint provenance')
    p.add_argument('--from-routed',action='store_true',help='Revalidate and export a routed checkpoint whose RTL/XDC provenance is unchanged')
    p.add_argument('--vivado',default=os.environ.get('VIVADO') or shutil.which('vivado') or shutil.which('vivado.bat') or 'C:/AMDDesignTools/2025.2/Vivado/bin/vivado.bat')
    a=p.parse_args(); dest=ROOT/'build/physical_runtime';dest.mkdir(parents=True,exist_ok=True)
    if a.from_synth or a.from_routed:
        if a.from_synth and a.from_routed:p.error('Choose one checkpoint stage')
        if a.project_only:p.error('--from-synth and --project-only are incompatible')
        prior=json.loads((dest/'execution.json').read_text())
        if prior.get('status')=='running':p.error('The previous build is still running')
        previous_hashes=json.loads((dest/'source_sha256.json').read_text())
        required={name:digest for name,digest in previous_hashes.items() if Path(name).suffix in ('.vhd','.xdc') or Path(name).name in ('create_physical_project.tcl','aurora_common.tcl','generate_aurora_adapter.py')}
        changed=[name for name,digest in required.items() if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
        dcp=dest/('obsidian_benchmark_routed.dcp' if a.from_routed else 'obsidian_benchmark_synth.dcp')
        started=datetime.datetime.fromisoformat(prior['started_at_utc']).timestamp()
        if changed or not dcp.is_file() or dcp.stat().st_mtime<started:p.error('Checkpoint/RTL provenance mismatch: '+str(changed))
        checkpoint_proof=dict(stage='routed' if a.from_routed else 'synthesized',previous_started_at_utc=prior['started_at_utc'],checkpoint_sha256=hashlib.sha256(dcp.read_bytes()).hexdigest(),verified_implementation_inputs=required)
    if (dest/'execution.json').exists():
        old=json.loads((dest/'execution.json').read_text())
        stamp=old.get('started_at_utc','previous').replace(':','').replace('.','_').replace('+','_')
        archive=dest/'attempts'/stamp;archive.mkdir(parents=True,exist_ok=True)
        for f in list(dest.glob('*.rpt'))+[dest/n for n in ('build.log','execution.json','build_manifest.txt','source_sha256.json','artifacts_sha256.json')]:
            if f.is_file():shutil.copy2(f,archive/f.name)
        for name in ('obsidian_benchmark.bit','obsidian_benchmark.ltx'):
            f=dest/name
            if f.exists():f.replace(archive/name)
    sources=sorted([*(ROOT/'rtl').rglob('*.vhd'),*(ROOT/'constraints').glob('*.xdc'),
        *(ROOT/'scripts'/n for n in ('create_physical_project.tcl','build_physical.tcl','build.tcl','aurora_common.tcl','generate_aurora_adapter.py'))])
    hashes={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sources}
    (dest/'source_sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
    env=os.environ.copy();env['PATH']=str(ROOT/'scripts/windows_compat')+os.pathsep+env.get('PATH','')
    env['OBSIDIAN_BUILD_PYTHON']=sys.executable
    if a.reuse_ip:env['OBSIDIAN_REUSE_IP']='1'
    else:env.pop('OBSIDIAN_REUSE_IP',None)
    if a.from_synth:env['OBSIDIAN_FROM_SYNTH']='1'
    else:env.pop('OBSIDIAN_FROM_SYNTH',None)
    if a.from_routed:env['OBSIDIAN_FROM_ROUTED']='1'
    else:env.pop('OBSIDIAN_FROM_ROUTED',None)
    if a.synth_only: env['OBSIDIAN_SYNTH_ONLY']='1'
    else: env.pop('OBSIDIAN_SYNTH_ONLY',None)
    script='create_physical_project.tcl' if a.project_only else 'build_physical.tcl'
    command=[a.vivado,'-mode','batch','-nojournal','-nolog','-source',str(ROOT/'scripts'/script)]
    evidence=dict(started_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),command=command,hardware_programmed=False,status='running')
    if a.from_synth or a.from_routed:evidence['checkpoint_proof']=checkpoint_proof
    record=dest/'execution.json';record.write_text(json.dumps(evidence,indent=2))
    with (dest/'build.log').open('w') as log:
        result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    text=(dest/'build.log').read_text(errors='replace')
    changed=[name for name,digest in hashes.items() if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
    manifest=(dest/'build_manifest.txt').read_text() if (dest/'build_manifest.txt').exists() else ''
    ok=result.returncode==0 and 'ERROR:' not in text and not changed
    if not a.project_only and not a.synth_only: ok &= 'status=implemented_timing_pass_bitstream_generated' in manifest
    evidence.update(finished_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),returncode=result.returncode,status='passed' if ok else 'failed',sources_changed=changed)
    record.write_text(json.dumps(evidence,indent=2)+'\n')
    if ok:
        artifacts={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in dest.iterdir() if f.suffix in ('.bit','.ltx','.rpt')}
        (dest/'artifacts_sha256.json').write_text(json.dumps(artifacts,indent=2)+'\n')
    print(json.dumps(evidence,indent=2));return 0 if ok else 1
if __name__=='__main__':sys.exit(main())
