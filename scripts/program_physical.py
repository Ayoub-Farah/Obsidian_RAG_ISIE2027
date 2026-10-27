"""Explicitly load the accepted common BIT/LTX on three FPGA SRAMs, then initialize.

Never called by builds or campaigns. Does not write configuration flash.
"""
from pathlib import Path
import argparse, datetime, hashlib, json, os, re, shutil, subprocess
from run_physical_campaign import ROOT, tq


def render_program(targets, image_dir):
    if len(targets) != 3 or len(set(targets)) != 3 or any(not re.fullmatch(r'[A-Za-z0-9]+', t) for t in targets):
        raise ValueError('Three distinct alphanumeric cable serials required, in ring order')
    return f'''source {tq(ROOT/'scripts/physical_hw.tcl')}
set physical_hw::targets {{{' '.join(targets)}}}
set physical_hw::ltx {tq(image_dir/'obsidian_benchmark.ltx')}
set bit {tq(image_dir/'obsidian_benchmark.bit')}
open_hw_manager
connect_hw_server
# Preflight all three devices before modifying any FPGA.
foreach serial $physical_hw::targets {{
 set ts [get_hw_targets */$serial]
 if {{[llength $ts]!=1}} {{error "Missing/ambiguous cable $serial"}}
 open_hw_target [lindex $ts 0]
 set ds [get_hw_devices -of_objects [current_hw_target]]
 if {{[llength $ds]!=1 || [get_property PART [lindex $ds 0]] ne "xc7a35t"}} {{error "Unexpected FPGA on $serial"}}
 close_hw_target
}}
foreach serial $physical_hw::targets {{
 open_hw_target [lindex [get_hw_targets */$serial] 0]
 set d [lindex [get_hw_devices -of_objects [current_hw_target]] 0]
 set_property PROGRAM.FILE $bit $d
 set_property PROBES.FILE $physical_hw::ltx $d
 puts "PROGRAM_BEGIN $serial";flush stdout
 program_hw_devices $d
 refresh_hw_device $d
 puts "PROGRAM_COMPLETE $serial";flush stdout
 close_hw_target
}}
physical_hw::initialize
foreach serial $physical_hw::targets {{puts "PROGRAMMED_IDLE $serial [format %064llx [physical_hw::status $serial]]"}}
close_hw_manager
puts "PHYSICAL_PROGRAM_COMPLETE";flush stdout
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--targets', nargs=3, default=['OBS001A','OBS003A','OBS002A'])
    p.add_argument('--image-dir', type=Path, default=ROOT/'build/physical_runtime')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    try:
        if a.output.exists() and any(a.output.iterdir()):
            raise ValueError('Use a new empty output directory')
        script = render_program(a.targets, a.image_dir)
        digests = {}
        if not a.dry_run:
            execution = json.loads((a.image_dir/'execution.json').read_text())
            manifest = (a.image_dir/'build_manifest.txt').read_text()
            hashes = json.loads((a.image_dir/'artifacts_sha256.json').read_text())
            if execution.get('status') != 'passed' or 'schema=physical_v3' not in manifest or 'status=implemented_timing_pass_bitstream_generated' not in manifest:
                raise ValueError('An accepted physical_v3 image is required')
            for name in ('obsidian_benchmark.bit','obsidian_benchmark.ltx'):
                digests[name] = hashlib.sha256((a.image_dir/name).read_bytes()).hexdigest()
                if hashes.get(name) != digests[name]:
                    raise ValueError('Artifact SHA256 mismatch: '+name)
    except (ValueError, OSError, KeyError) as e:
        p.error(str(e))
    a.output.mkdir(parents=True, exist_ok=True)
    script_path = a.output/'program.tcl';script_path.write_text(script, encoding='utf-8')
    record = dict(schema='physical_programming_v1', status='dry_run' if a.dry_run else 'running',
                  targets=dict(zip('ABC',a.targets)), operation='program_fpga_sram', flash_memory_written=False,
                  artifact_sha256=digests, raw_counter_origins_reset=True,
                  started_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    record_path = a.output/'programming.json'
    record_path.write_text(json.dumps(record,indent=2)+'\n')
    if a.dry_run:
        print(script_path);return
    vivado = os.environ.get('VIVADO') or shutil.which('vivado') or shutil.which('vivado.bat') or 'C:/AMDDesignTools/2025.2/Vivado/bin/vivado.bat'
    with (a.output/'programming.log').open('w') as log:
        result = subprocess.run([vivado,'-mode','batch','-nojournal','-nolog','-source',str(script_path.resolve())],
                                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    transcript = (a.output/'programming.log').read_text(errors='replace')
    passed = result.returncode == 0 and '\nPHYSICAL_PROGRAM_COMPLETE' in transcript and not re.search(r'^ERROR:',transcript,re.M)
    record.update(status='passed' if passed else 'failed',returncode=result.returncode,
                  finished_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    record_path.write_text(json.dumps(record,indent=2)+'\n')
    if not passed:
        raise RuntimeError('Programming/initialization failed; inspect programming.log')
    print(record_path)


if __name__ == '__main__':
    main()
