"""Run source-matched PTP RTL, Python contracts and CT/RAG sync regressions."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from ptp_capacity_cases import capacity_cases
PATTERN='(tb_ptp_.*|tb_sync_.*|tb_management_codec|tb_codec_equivalence|tb_physical_system|tb_physical_holdover)'
SINGLE_CASES=[
    'tb_ptp_single_node','tb_ptp_event_journal','tb_ptp_registers',
    'tb_ptp_link','tb_ptp_link_bram_equivalence','tb_ptp_observation',
    'tb_codec_stream_crc','tb_codec_equivalence','tb_management_codec',
    'tb_sync_median_serial','tb_sync_k1_optimization','tb_sync_median_enable',
    'tb_sync_system','tb_sync_stalls','tb_sync_bounded','tb_sync_median',
    'tb_physical_system','tb_physical_holdover','tb_crc']


def dependency_graph(names):
    """Conservative file graph for portable direct entity/package references.

    A changed control wrapper need not invalidate a test of the unchanged core.
    Every file reachable by a selected test must match its compiled snapshot.
    """
    texts={n:(ROOT/n).read_text(encoding='utf-8') for n in names}
    entities={};packages={}
    for n,text in texts.items():
        for entity in re.findall(r'\bentity\s+(\w+)\s+is',text,re.I):entities[entity.lower()]=n
        for package in re.findall(r'\bpackage\s+(?!body\b)(\w+)\s+is',text,re.I):packages[package.lower()]=n
    graph={}
    for n,text in texts.items():
        refs=[entities[v.lower()] for v in re.findall(r'\bentity\s+work\.(\w+)',text,re.I) if v.lower() in entities]
        refs += [packages[v.lower()] for v in re.findall(r'\buse\s+work\.(\w+)\.',text,re.I) if v.lower() in packages]
        if re.search(r'\bcomponent\s+\w+\s+is',text,re.I):
            refs += list(names)  # No assumption about component binding.
        graph[n]=set(refs)-{n}
    return entities,graph


def reachable(root,graph):
    result=set();pending=[root]
    while pending:
        n=pending.pop()
        if n not in result:result.add(n);pending.extend(graph[n]-result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--collect-existing-rtl',action='store_true')
    p.add_argument('--scope',choices=('single','capacity','emulation'),default='single')
    p.add_argument('--capacity',type=int)
    p.add_argument('--rtl-dir',type=Path)
    p.add_argument('--supplement-rtl-dir',type=Path,action='append',default=[])
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.scope=='capacity' and (a.capacity is None or not 2<=a.capacity<=20):
        p.error('--scope capacity requires --capacity 2..20')
    if a.scope=='capacity':
        a.rtl_dir=a.rtl_dir or ROOT/'build/ptp_capacity_validation'/f'k{a.capacity}'
        a.output=a.output or ROOT/'build/validation/ptp_capacity'/f'k{a.capacity}'
    else:
        a.rtl_dir=a.rtl_dir or ROOT/'build'/('ptp_single_node_validation_final' if a.scope=='single' else 'ptp_validation')
        a.output=a.output or ROOT/'build/validation'/('ptp_single_node' if a.scope=='single' else 'ptp_emulation')
    a.output.mkdir(parents=True,exist_ok=True)
    marker=a.output/'validation.json'
    record=dict(status='running',scope=a.scope,recorded_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    marker.write_text(json.dumps(record,indent=2)+'\n')
    try:
        execute(a)
    except Exception as error:
        record.update(status='failed',error=str(error))
        marker.write_text(json.dumps(record,indent=2)+'\n')
        raise


def execute(a):
    capacity_specs=capacity_cases(a.capacity) if a.scope=='capacity' else {}
    def run(command, dest):
        with dest.open('w') as log:
            r=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        if r.returncode:
            raise RuntimeError(f'Validation failed: {dest}')
    run([sys.executable,'-m','unittest','discover','-s','sim','-p','test_*.py','-v'],a.output/'python.log')
    if not a.collect_existing_rtl:
        selected=list(capacity_specs) if a.scope=='capacity' else SINGLE_CASES
        pattern='('+'|'.join(selected)+')' if a.scope in ('single','capacity') else PATTERN
        command=[sys.executable,'scripts/run_vivado_tests.py','--output-dir',str(a.rtl_dir),'--only',pattern]
        if a.scope=='capacity':command+=['--ptp-capacity',str(a.capacity)]
        run(command,a.output/'runner.log')
    snapshots=[]
    for folder in [a.rtl_dir,*a.supplement_rtl_dir]:
        hashes=json.loads((folder/'source_sha256.json').read_text())
        results=json.loads((folder/'results.json').read_text())
        proof=json.loads((folder/'execution.json').read_text())
        if proof.get('status')!='passed' or any(proof.get(key)!=hashlib.sha256((folder/file).read_bytes()).hexdigest() for key,file in (('source_snapshot_sha256','source_sha256.json'),('results_sha256','results.json'))):
            raise RuntimeError('Incomplete or inconsistent RTL execution: '+str(folder))
        snapshots.append((folder,hashes,{r['name'] for r in results if r['passed']},proof['cases']))
    names=set().union(*(set(h) for _,h,_,_ in snapshots));entities,graph=dependency_graph(names)
    inventory={str(f.relative_to(ROOT)) for d in ('protocol','links','sync','system') for f in (ROOT/'rtl'/d).glob('*.vhd')}
    inventory.update(str(f.relative_to(ROOT)) for pattern in ('tb_*.vhd','*_model.vhd') for f in (ROOT/'sim').glob(pattern))
    inventory.update(str(f.relative_to(ROOT)) for f in (ROOT/'sim/equivalence').glob('*.vhd'))
    if any(set(hashes)!=inventory for _,hashes,_,_ in snapshots):
        raise RuntimeError('Compiled RTL source inventory differs from the current inventory')
    current={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
    case_sources={};selected={}
    required=['tb_ptp_observation','tb_ptp_registers','tb_ptp_link','tb_ptp_runtime_chain',
              *[f'tb_ptp_chain_{n}' for n in (3,6,10,20,30,40,50,60,180)],
              'tb_ptp_chain_phased','tb_ptp_chain_asymmetry','tb_sync_system','tb_sync_stalls','tb_sync_bounded',
              'tb_sync_median','tb_sync_median_enable','tb_management_codec','tb_codec_equivalence','tb_physical_system','tb_physical_holdover']
    if a.scope=='single':required=SINGLE_CASES
    elif a.scope=='capacity':required=list(capacity_specs)
    for n in required:
        entity='tb_ptp_chain' if n.startswith('tb_ptp_chain_') else 'tb_sync_system' if n in ('tb_sync_stalls','tb_sync_bounded') else 'tb_physical_system' if n=='tb_physical_holdover' else n
        if a.scope=='capacity':entity=capacity_specs[n]['entity']
        used=reachable(entities[entity],graph)
        for folder,hashes,passed,cases in reversed(snapshots):
            expected=dict(entity=entity,generics='')
            if n=='tb_sync_stalls':expected['generics']='G_STALL=>true'
            elif n=='tb_sync_bounded':expected['generics']='G_TEST_BOUNDED=>true'
            elif n=='tb_physical_holdover':expected['generics']='G_TEST_HOLDOVER=>true'
            elif n=='tb_ptp_chain_phased':expected['generics']='G_NODES=>10,G_PHASED=>true,G_DRIFT=>2000'
            elif n=='tb_ptp_chain_asymmetry':expected['generics']='G_NODES=>10,G_ASYMMETRY=>true'
            elif n.startswith('tb_ptp_chain_'):expected['generics']='G_NODES=>'+n.rsplit('_',1)[1]
            if a.scope=='capacity':expected=capacity_specs[n]
            matched=cases.get(n)==expected and all(hashes.get(f)==current[f] for f in used)
            if all(prefix+n in passed for prefix in ('elab_','sim_')) and matched:
                log=folder/('sim_'+n+'.log');text=log.read_text(errors='replace')
                if not re.search(r'\bPASS\b',text) or re.search(r'(?:Failure:|Fatal:|ERROR:)',text):continue
                case_sources[n]=dict(evidence_directory=str(folder),compiled_source_sha256={f:hashes[f] for f in sorted(used)})
                selected[n]=folder;shutil.copy2(log,a.output/log.name);break
        else:raise RuntimeError('Missing successful source-matched RTL case: '+n)
    for name in ('results.json','source_sha256.json'):
        shutil.copy2(a.rtl_dir/name,a.output/name)
    (a.output/'case_sources.json').write_text(json.dumps(case_sources,indent=2)+'\n')
    for n in (('3','10','60','180','asymmetry','phased') if a.scope=='emulation' else ()):
        run([sys.executable,'scripts/analyze_ptp.py','simulation',str(selected['tb_ptp_chain_'+n]/f'sim_tb_ptp_chain_{n}.log'),
             '--output',str(a.output/f'chain_{n}'),'--plot'],a.output/f'export_{n}.log')
    report=dict(schema='ptp_validation_v1',recorded_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                status='passed',rtl_cases=required,source_hashes_verified=True,
                verification_scope='per-case transitive RTL dependencies with exact compiled hashes; see case_sources.json',
                scope=a.scope,
                physical_boards_simulated=3,modules_per_board=1 if a.scope=='single' else a.capacity,
                max_synchronized_logical_nodes=3 if a.scope=='single' else 3*a.capacity if a.scope=='capacity' else 180,
                hardware_programmed=False,hardware_validation='not_executed',
                synthesis_and_timing='See separate build execution records; not implied by simulation')
    count=re.search(r'Ran (\d+) tests',(a.output/'python.log').read_text(errors='replace'))
    report['python_tests']=int(count.group(1)) if count else None
    (a.output/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
