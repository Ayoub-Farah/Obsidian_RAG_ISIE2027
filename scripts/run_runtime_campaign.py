#!/usr/bin/env python3
"""Configure and run three already programmed runtime RAG FPGA images via JTAG."""
from pathlib import Path
import argparse, hashlib, json, os, re, shutil, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]

def partitions(nodes,capacity):
    if capacity<3 or capacity>30 or capacity%3:
        raise ValueError('Capacity must be 3,6,...,30')
    if not 3<=nodes<=capacity:
        raise ValueError('Requested N must be between 3 and the bitstream capacity')
    q,r=divmod(nodes,3)
    return [q+(i<r) for i in range(3)]

def config_word(mode,nodes,base,local):
    if mode not in (0,2) or not 3<=nodes<=30 or not 1<=local<=10 or base<0 or base+local>nodes:
        raise ValueError('Invalid runtime configuration')
    return mode | nodes<<2 | base<<8 | local<<14

def tq(path):
    value=Path(path).resolve().as_posix()
    if any(c in value for c in '{}\n\r'):
        raise ValueError('Unsupported Tcl path characters')
    return '{'+value+'}'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--nodes',type=int,required=True)
    p.add_argument('--mode',choices=['RAG_C','RAG_D'],required=True)
    p.add_argument('--capacity',type=int,required=True,help='Compiled capacity across three cards')
    p.add_argument('--targets',nargs=3,default=['OBS001A','OBS003A','OBS002A'],help='Cable serials in actual forward ring order')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--program',action='store_true',help='Program the runtime image on all three cards first')
    p.add_argument('--dry-run',action='store_true',help='Write reviewable Tcl and metadata without contacting hardware')
    a=p.parse_args()
    try:
        counts=partitions(a.nodes,a.capacity)
        if len(set(a.targets))!=3 or any(not re.fullmatch(r'[A-Za-z0-9]+',s) for s in a.targets):
            raise ValueError('Specify three distinct alphanumeric cable serials')
    except ValueError as e:p.error(str(e))
    mode=0 if a.mode=='RAG_C' else 2
    profile=ROOT/'build'/f'rag_m2_n{a.capacity}_b0_l{a.capacity//3}_d6_r2_c128_runtime'
    bit=profile/'obsidian_benchmark.bit';ltx=profile/'obsidian_benchmark.ltx'
    if not a.dry_run:
        manifest=(profile/'build_manifest.txt').read_text() if (profile/'build_manifest.txt').exists() else ''
        if not bit.is_file() or not ltx.is_file() or 'status=implemented_timing_pass_bitstream_generated' not in manifest:
            p.error('A runtime image accepted by timing/DRC is required: '+str(profile))
    out=a.output.resolve()
    if out.exists() and any(out.iterdir()):p.error('Use a new empty output directory to preserve prior evidence')
    out.mkdir(parents=True,exist_ok=True)
    # Source the existing stable two-pass journal reader inside this connection.
    dump=(ROOT/'scripts/dump_log.tcl').read_text().replace('open_hw_manager','').replace('connect_hw_server','')
    dump=dump.replace('source [file join [file dirname [info script]] hw_helpers.tcl]', 'source '+tq(ROOT/'scripts/hw_helpers.tcl'))
    (out/'dump_session.tcl').write_text(dump)
    plan=[];base=0
    for index,(serial,count) in enumerate(zip(a.targets,counts)):
        plan.append(dict(board=chr(65+index),serial=serial,base=base,local=count,word=config_word(mode,a.nodes,base,count)))
        base+=count
    tcl='source '+tq(ROOT/'scripts/hw_helpers.tcl')+'\nopen_hw_manager\nconnect_hw_server\n'
    tcl+='set bit '+tq(bit)+'\nset ltx '+tq(ltx)+'\n'
    tcl+='''proc select_board {serial} {
 global ltx
 set ts [get_hw_targets */$serial]
 if {[llength $ts]!=1} {error "Expected exactly one cable $serial: $ts"}
 open_hw_target [lindex $ts 0]
 set ds [get_hw_devices -of_objects [current_hw_target]]
 if {[llength $ds]!=1 || [get_property PART [lindex $ds 0]] ne "xc7a35t"} {error "Unexpected device $ds"}
 set d [lindex $ds 0]
 set_property PROBES.FILE $ltx $d
 return $d
}
proc select_vio {serial} {
 set d [select_board $serial]
 refresh_hw_device $d
 set vs [get_hw_vios -of_objects $d]
 if {[llength $vs]!=1} {error "Expected one runtime VIO"}
 set v [lindex $vs 0]
 obsidian_hw::vio_probe $v out 4
 return $v
}
'''
    if a.program:
        for b in plan:
            tcl+=f'set d [select_board {b["serial"]}]\nset_property PROGRAM.FILE $bit $d\nprogram_hw_devices $d\nclose_hw_target\n'
    # Stop all nodes before asserting resets or rewriting configuration.
    for b in plan:
        tcl+=f'set v [select_vio {b["serial"]}]\nobsidian_hw::write_output $v 1 0\nobsidian_hw::write_output $v 2 1\nclose_hw_target\n'
    tcl+='after 100\n'
    for b in plan:
        tcl+=f'''set v [select_vio {b['serial']}]
obsidian_hw::write_output $v 0 1
obsidian_hw::write_output $v 4 {b['word']:08x}
obsidian_hw::write_output $v 2 0
close_hw_target
'''
    for b in plan:
        tcl+=f'''set v [select_vio {b['serial']}]
obsidian_hw::write_output $v 0 0
after 100
refresh_hw_vio $v
set links [obsidian_hw::read_input $v 4]
set status [obsidian_hw::read_input $v 0]
if {{[expr 0x$links]!=3 || ([expr 0x$status] & (1<<38))!=0}} {{error "Links or config invalid: {b['serial']} $links $status"}}
if {{(([expr 0x$status] >> 192) & 0xffffffff)!={a.nodes} || (([expr 0x$status] >> 224) & 0xffffffff)!={b['base']} || (([expr 0x$status] >> 160) & 0xffffffff)!={mode}}} {{error "Active configuration readback mismatch"}}
puts "CONFIGURED {b['serial']} N={a.nodes} mode={mode} base={b['base']} local={b['local']}"
close_hw_target
'''
    tcl+=f'set v [select_vio {plan[0]["serial"]}]\nobsidian_hw::write_output $v 1 1\nclose_hw_target\nafter 2000\n'
    tcl+='''proc collect {serial ltx output board dump_script} {
 set d [select_board $serial]
 close_hw_target
 set ::env(OBSIDIAN_HW_TARGET) "*/$serial"
 set argv [list $ltx $output $d $board]
 source $dump_script
 close_hw_target
}
'''
    for b in plan:
        tcl+=f'collect {b["serial"]} $ltx '+tq(out/(b['board']+'_log.json'))+' '+b['board']+' '+tq(out/'dump_session.tcl')+'\n'
    tcl+='close_hw_manager\nputs "RUNTIME_CAMPAIGN_COLLECTED"\n'
    (out/'run.tcl').write_text(tcl)
    metadata=dict(run_id=out.name,mode=a.mode,N=a.nodes,D=6,R=2,line_rate='1.25Gbps',capacity=a.capacity,plan=plan,
        primary_metric='module_1_return_crc_validated',virtual_model_id='E1_latency37_cc5000_gap2_uncalibrated',
        measurement_uncertainty_ns='not_calibrated',source='dry_run' if a.dry_run else 'hardware_jtag',
        bitstream_sha256=hashlib.sha256(bit.read_bytes()).hexdigest() if bit.is_file() else 'not_built')
    metadata['bitstream_id']=metadata['bitstream_sha256']
    (out/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    if a.dry_run:
        print(json.dumps(metadata,indent=2));print(out/'run.tcl');return
    vivado=os.environ.get('VIVADO') or shutil.which('vivado') or shutil.which('vivado.bat')
    if not vivado:p.error('Set VIVADO or add Vivado 2025.2 to PATH')
    env=os.environ.copy();env['PATH']=str(ROOT/'scripts/windows_compat')+os.pathsep+env.get('PATH','')
    with (out/'vivado.log').open('w') as log:
        result=subprocess.run([vivado,'-mode','batch','-nojournal','-nolog','-source',str(out/'run.tcl')],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    transcript=(out/'vivado.log').read_text(errors='replace')
    if result.returncode or 'RUNTIME_CAMPAIGN_COLLECTED' not in transcript or re.search(r'^ERROR:',transcript,re.M):
        raise RuntimeError('Hardware command failed; see '+str(out/'vivado.log'))
    sys.path.insert(0,str(ROOT/'scripts'));from decode_log import decode_dump,FIELDS
    import csv
    all_rows=[];summary={}
    for b in plan:
        rows,unused=decode_dump(json.loads((out/(b['board']+'_log.json')).read_text()),metadata)
        if len(rows)!=128 or [r['cycle_id'] for r in rows]!=list(range(128)) or [r['log_sequence'] for r in rows]!=list(range(1,129)):
            raise RuntimeError('Incomplete journal for '+b['board'])
        if any(r['status']!='ok' or r['sync_locked']!=1 or r['crc_errors_cumulative']!=0 or r['N']!=a.nodes or r['mode']!=a.mode for r in rows):
            raise RuntimeError('Failed hardware cycles for '+b['board'])
        if b['board']=='A' and any(not r['T_return_us'] or float(r['T_return_us'])<=0 or float(r['T_return_us'])>float(r['T_drained_us']) for r in rows):
            raise RuntimeError('Invalid module 1 packet return measurement')
        summary[b['board']]=dict(serial=b['serial'],cycles=len(rows),status='ok')
        if b['board']=='A':
            values=[float(r['T_return_us']) for r in rows]
            summary[b['board']]['T_return_us']=dict(min=min(values),mean=sum(values)/len(values),max=max(values))
        all_rows.extend(rows)
    with (out/'times.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(all_rows)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()

