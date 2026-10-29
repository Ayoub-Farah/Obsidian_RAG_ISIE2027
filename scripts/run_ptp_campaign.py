"""Configure, observe or collect already loaded PTP images. Never programs FPGA."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from ptp_config import normalize, registers, locate, config_id


def tq(path):
    value = Path(path).resolve().as_posix()
    if any(c in value for c in '{}\r\n'):
        raise ValueError('Unsupported Tcl path')
    return '{'+value+'}'


def render(action, cfg, targets, image, output, node=None, timeout_ms=300000):
    if len(set(targets)) != 3 or any(not re.fullmatch(r'[A-Za-z0-9]+', s) for s in targets):
        raise ValueError('Three distinct alphanumeric cable serials required')
    t = ['source '+tq(ROOT/'scripts/ptp_hw.tcl'), 'open_hw_manager', 'connect_hw_server',
         'set ptp_hw::targets {'+' '.join(targets)+'}', 'set ptp_hw::ltx '+tq(image/'obsidian_ptp.ltx'),
         f'set ptp_hw::timeout_ms {timeout_ms}']
    if action in ('configure', 'run'):
        t.append('ptp_hw::stop_all')
        for b, serial in enumerate(targets):
            t.append(f'ptp_hw::stage {serial} {b} '+'{'+' '.join(f'{v:016x}' for v in registers(cfg, b))+'} '+str(cfg['capacity']))
        for b in (1, 2, 0):
            t.append(f'ptp_hw::pulse {targets[b]} 4')
    if action in ('configure', 'run', 'start', 'observe'):
        t.append(f'ptp_hw::check_active {config_id(cfg):016x} {cfg["nodes"]} {cfg["capacity"]}')
    if node is not None and action in ('observe', 'run'):
        selected = locate(cfg, node)
        t.append(f'ptp_hw::observe {targets[selected["board_index"]]} {selected["node_id"]}')
    if action in ('start', 'run'):
        if action == 'start':
            for b in (1,2):
                t.append(f'ptp_hw::pulse {targets[b]} 5')
        t.append(f'ptp_hw::pulse {targets[0]} 5')
        t.append(f'ptp_hw::wait_running {int(cfg["duration_ticks"] != 0)}')
    if action == 'stop':
        t.append('ptp_hw::stop_all')
    if action == 'collect':
        for board, serial in zip('ABC', targets):
            t.append('ptp_hw::collect '+serial+' '+tq(output/f'{board}_page.json'))
    if action == 'status':
        t.append('foreach serial $ptp_hw::targets {puts "PTP_STATUS $serial [format %064llx [ptp_hw::status $serial]]"}')
    t += ['close_hw_manager', 'puts "PTP_COMMAND_COMPLETE"']
    return '\n'.join(t)+'\n'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('configure', 'run', 'start', 'stop', 'status', 'collect', 'observe'))
    p.add_argument('--config', type=Path, default=ROOT/'config/ptp_emulation_3.example.json')
    p.add_argument('--node', type=int)
    p.add_argument('--targets', nargs=3, default=['OBS001A', 'OBS003A', 'OBS002A'])
    p.add_argument('--image-dir', type=Path, default=ROOT/'build/ptp_single_node_final')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--timeout-seconds', type=int, default=300)
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    try:
        cfg = normalize(json.loads(a.config.read_text(encoding='utf-8')))
        if a.action == 'observe' and a.node is None:
            raise ValueError('observe requires --node M (integer 1..N)')
        if a.timeout_seconds <= 0:
            raise ValueError('timeout must be positive')
        selected = locate(cfg, a.node) if a.node is not None else None
        if a.output.exists() and any(a.output.iterdir()):
            raise ValueError('Use a new empty output directory')
        script = render(a.action, cfg, a.targets, a.image_dir, a.output, a.node, a.timeout_seconds*1000)
        if not a.dry_run:
            proof = json.loads((a.image_dir/'execution.json').read_text())
            if proof.get('status') != 'passed' or proof.get('validation_stage') != 'routed_bitstream' or proof.get('capacity') != cfg['capacity']:
                raise ValueError('A validated PTP BIT/LTX matching capacity is required')
            for name in ('obsidian_ptp.bit', 'obsidian_ptp.ltx'):
                digest = hashlib.sha256((a.image_dir/name).read_bytes()).hexdigest()
                if digest != proof['artifacts_sha256'].get(name):
                    raise ValueError(f'Build artifact hash mismatch: {name}')
    except (ValueError, OSError, KeyError) as e:
        p.error(str(e))
    a.output.mkdir(parents=True, exist_ok=True)
    (a.output/'run.tcl').write_text(script, encoding='utf-8')
    metadata = dict(schema='ptp_campaign_v1', source='dry_run' if a.dry_run else 'hardware_jtag',
                    configuration=cfg, config_id=f'{config_id(cfg):016x}', selection=selected,
                    created_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    hardware_programmed=False, global_hardware_clock_error=None)
    (a.output/'campaign.json').write_text(json.dumps(metadata, indent=2)+'\n')
    if selected:
        print(f'{selected["module"]}: carte {selected["board"]}, index local {selected["local_index"]}, TP24/TP16; reference M1 sur A TP23/TP15')
    if a.dry_run:
        print(a.output/'run.tcl')
        return
    vivado = os.environ.get('VIVADO') or shutil.which('vivado') or shutil.which('vivado.bat') or 'C:/AMDDesignTools/2025.2/Vivado/bin/vivado.bat'
    with (a.output/'hardware.log').open('w') as log:
        result = subprocess.run([vivado, '-mode', 'batch', '-nojournal', '-nolog', '-source', str((a.output/'run.tcl').resolve())], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    text = (a.output/'hardware.log').read_text(errors='replace')
    if result.returncode or 'PTP_COMMAND_COMPLETE' not in text or re.search(r'^ERROR:', text, re.M):
        raise RuntimeError('PTP JTAG command failed; inspect hardware.log')


if __name__ == '__main__':
    main()
