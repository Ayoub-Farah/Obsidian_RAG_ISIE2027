from pathlib import Path
import importlib.util
import argparse
import os
import shutil
import hashlib
import json
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description='Validate portable RTL and cycle equivalence with Vivado XSim.')
parser.add_argument('--vivado-bin',type=Path)
parser.add_argument('--only',default='.*',help='regular expression for testbench names')
parser.add_argument('--output-dir',type=Path,default=ROOT/'build/xsim_tests')
args=parser.parse_args()
DEST=args.output_dir.resolve()
DEST.mkdir(parents=True, exist_ok=True)
exe=os.environ.get('VIVADO') or shutil.which('vivado') or shutil.which('vivado.bat')
BIN=args.vivado_bin or (Path(exe).parent if exe else Path('C:/AMDDesignTools/2025.2/Vivado/bin'))
if not (BIN/'xvhdl.bat').is_file(): parser.error('Set VIVADO or --vivado-bin to Vivado 2025.2 bin directory.')
spec = importlib.util.spec_from_file_location('portable_tests', ROOT/'tools/run_tests.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
sources = [p for d in ('protocol','links','sync','system') for p in (ROOT/'rtl'/d).glob('*.vhd')]
sources += list((ROOT/'sim').glob('tb_*.vhd'))
sources += list((ROOT/'sim').glob('*_model.vhd'))
sources += list((ROOT/'sim/equivalence').glob('*.vhd'))
sources = mod.sources_in_order(sources)
# Invalidate old successes before replacing their source fingerprints. A stopped
# rerun must never pair a new fingerprint file with the previous run's results.
results = []
(DEST/'results.json').write_text(json.dumps(results))
proof=dict(status='running',runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
(DEST/'execution.json').write_text(json.dumps(proof,indent=2))
hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
(DEST/'source_sha256.json').write_text(json.dumps(hashes,indent=2))

def run(name, tool, args, timeout=600, require_pass=False):
    started = time.time()
    with (DEST/(name+'.log')).open('w') as f:
        result = subprocess.run([str(BIN/(tool+'.bat')), *args], cwd=DEST,
                                stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
    log = (DEST/(name+'.log')).read_text(errors='replace')
    passed = result.returncode == 0 and not re.search(r'(?:Failure:|Fatal:|ERROR:)', log)
    if require_pass: passed &= bool(re.search(r'\bPASS\b', log))
    entry = dict(name=name, passed=passed, seconds=round(time.time()-started,1))
    results.append(entry)
    (DEST/'results.json').write_text(json.dumps(results, indent=2))
    print(entry, flush=True)
    if not passed: raise RuntimeError(name + ' failed: ' + log[-2500:])

run('compile', 'xvhdl', ['--2008', *map(str,sources)])
cases = [(name, name, '') for name in ('tb_physical_system','tb_physical_node','tb_physical_fifo','tb_sync_median','tb_crc','tb_links','tb_data_frame_filter','tb_management_codec','tb_rag_integrity',
          'tb_rag_c_useful','tb_rag_ring','tb_sync_system','tb_benchmark_fault')]
cases += [('tb_ptp_observation','tb_ptp_observation','')]
cases += [('tb_sync_median_enable','tb_sync_median_enable','')]
cases += [('tb_codec_stream_crc','tb_codec_stream_crc','')]
cases += [(n,n,'') for n in ('tb_ptp_event_journal','tb_sync_median_serial','tb_sync_k1_optimization','tb_ptp_single_node')]
cases += [('tb_ptp_link_bram_equivalence','tb_ptp_link_bram_equivalence','')]
cases += [(n,n,'') for n in ('tb_ptp_registers','tb_ptp_link','tb_ptp_runtime_chain')]
cases += [(f'tb_ptp_chain_{n}','tb_ptp_chain',f'G_NODES=>{n}') for n in (3,6,10,20,30,40,50,60,180)]
cases += [('tb_ptp_chain_phased','tb_ptp_chain','G_NODES=>10,G_PHASED=>true,G_DRIFT=>2000'),
          ('tb_ptp_chain_asymmetry','tb_ptp_chain','G_NODES=>10,G_ASYMMETRY=>true')]
cases += [('tb_runtime_30','tb_runtime_system','G_TEST_RECORDS=>3'),
          ('tb_runtime_30_maintenance','tb_runtime_system','G_MAX_ONLY=>true')]
cases += [('tb_runtime_small','tb_runtime_system','G_CAPACITY_LOCAL=>2')]
cases += [('tb_physical_pages','tb_physical_system','G_TEST_PAGES=>true')]
cases += [('tb_physical_holdover','tb_physical_system','G_TEST_HOLDOVER=>true')]
cases += [(f'tb_physical_fault_{i}','tb_physical_integrity',f'G_FAULT=>{i}') for i in range(5)]
cases += [('tb_sync_stalls','tb_sync_system','G_STALL=>true'),
          ('tb_sync_bounded','tb_sync_system','G_TEST_BOUNDED=>true'),
          ('tb_integration_ragd','tb_benchmark_system','G_MODE=>2,G_LOCAL_NODES=>1,G_RECORDS=>12,G_ARM_DELAY=>10000')]
cases += [(name,name,'') for name in ('tb_codec_equivalence','tb_filter_eq_2','tb_filter_eq_16','tb_filter_eq_128','tb_filter_eq_2048')]
cases=[case for case in cases if re.fullmatch(args.only,case[0])]
proof['cases']={top:dict(entity=entity,generics=generics) for top,entity,generics in cases}
wrappers = ''
for top, entity, generics in cases:
    if generics:
        wrappers += f'entity {top} is end; architecture test of {top} is begin u:entity work.{entity} generic map({generics});end;\n'
(DEST/'test_tops.vhd').write_text(wrappers)
run('compile_tops','xvhdl',['--2008','test_tops.vhd'])
for top, _, _ in cases:
    run('elab_'+top, 'xelab', ['--debug','typical',top,'-s',top+'_snapshot'])
    run('sim_'+top, 'xsim', [top+'_snapshot','-runall'], timeout=3600 if top.startswith(('tb_runtime','tb_ptp_chain')) else 600, require_pass=True)

changed=[name for name,digest in hashes.items() if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
if changed: raise RuntimeError("Sources changed during validation: "+str(changed))
current_sources={str(p.relative_to(ROOT)) for d in ('protocol','links','sync','system') for p in (ROOT/'rtl'/d).glob('*.vhd')}
current_sources.update(str(p.relative_to(ROOT)) for pattern in ('tb_*.vhd','*_model.vhd') for p in (ROOT/'sim').glob(pattern))
current_sources.update(str(p.relative_to(ROOT)) for p in (ROOT/'sim/equivalence').glob('*.vhd'))
if current_sources!=set(hashes): raise RuntimeError('Source inventory changed during validation')
proof.update(status='passed',source_snapshot_sha256=hashlib.sha256((DEST/'source_sha256.json').read_bytes()).hexdigest(),results_sha256=hashlib.sha256((DEST/'results.json').read_bytes()).hexdigest())
(DEST/'execution.json').write_text(json.dumps(proof,indent=2)+'\n')
print("ALL_SELECTED_TESTS_PASSED",flush=True)
