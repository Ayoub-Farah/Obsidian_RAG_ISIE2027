"""Validate the physical benchmark and collect source-matched, real evidence."""
from pathlib import Path
import argparse,datetime,hashlib,json,re,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
REQUIRED=['tb_physical_system','tb_physical_node','tb_physical_fifo','tb_physical_pages','tb_physical_holdover',
          *[f'tb_physical_fault_{i}' for i in range(5)],'tb_crc','tb_management_codec','tb_sync_median','tb_sync_system','tb_sync_stalls','tb_sync_bounded','tb_codec_equivalence']

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--collect-existing-rtl',action='store_true',help='Accept existing PASS logs only if all compiled source hashes still match')
    a=p.parse_args();dest=ROOT/'reports/physical_validation';dest.mkdir(parents=True,exist_ok=True)
    commands=[]
    def run(command,log):
        result=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (dest/log).write_text(result.stdout,encoding='utf-8');commands.append(dict(command=command,returncode=result.returncode,log=log))
        if result.returncode:raise RuntimeError(f'Failed validation; inspect {dest/log}')
        return result.stdout
    pylog=run([sys.executable,'-m','unittest','discover','-s','sim','-p','test_*.py','-v'],'python.log')
    if not a.collect_existing_rtl:
        run([sys.executable,'scripts/run_vivado_tests.py','--only','(tb_physical_.*|tb_crc|tb_management_codec|tb_sync_.*|tb_codec_equivalence)'],'xsim_runner.log')
    results_dir=ROOT/'build/xsim_tests'
    hashes=json.loads((results_dir/'source_sha256.json').read_text());results=json.loads((results_dir/'results.json').read_text())
    changed=[name for name,digest in hashes.items() if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
    if changed:raise RuntimeError('RTL logs do not match current sources: '+str(changed))
    byname={r['name']:r for r in results}
    for case in ['compile','compile_tops',*[prefix+c for c in REQUIRED for prefix in ('elab_','sim_')]]:
        if not byname.get(case,{}).get('passed'):raise RuntimeError('Missing/failed evidence: '+case)
        log=results_dir/(case+'.log')
        text=log.read_text(errors='replace')
        if re.search(r'(?:Failure:|Fatal:|ERROR:)',text) or (case.startswith('sim_') and not re.search(r'\bPASS\b',text)):raise RuntimeError('Invalid evidence log: '+case)
        shutil.copy2(log,dest/log.name)
    for name in ('source_sha256.json','results.json'):shutil.copy2(results_dir/name,dest/name)
    csv_path=dest/'simulation.csv'
    run([sys.executable,'scripts/extract_physical_simulation.py',str(dest/'sim_tb_physical_system.log'),'--output',str(csv_path)],'simulation_export.log')
    run([sys.executable,'scripts/analyze_physical.py','plot',str(csv_path),'--output',str(dest/'simulation_durations.png')],'plot.log')
    run([sys.executable,'scripts/analyze_physical.py','fit-model',str(csv_path),'--output',str(dest/'simulation_model.json')],'model.log')
    count=re.search(r'Ran (\d+) tests',pylog)
    report=dict(recorded_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),status='passed',
        python_tests=int(count.group(1)) if count else None,rtl_cases=REQUIRED,compiled_source_hashes_verified=True,
        hardware_programmed=False,hardware_measurements=0,simulation_data='simulation.csv',commands=commands)
    (dest/'validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
