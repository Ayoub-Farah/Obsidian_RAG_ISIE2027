"""Sequential scope captures through an existing report-local hardware worker.

Never starts Vivado or programs/configures/resets/stops PTP. Probe placement and
output identity must be checked by the operator before --wiring-verified.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid

BOARDS = {'A': ('OBS001A', 0), 'B': ('OBS003A', 3), 'C': ('OBS002A', 6)}
FOLDERS = {
    0: '06_A_M1_verified', 1: '07_A_M2_verified', 2: '08_A_M3_verified',
    3: '09_B_M4', 4: '10_B_M5', 5: '11_B_M6',
    6: '12_C_M7', 7: '13_C_M8', 8: '14_C_M9',
}
CAPTURE = Path(__file__).with_name('ptp_scope_capture.py')


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def emit(**values):
    print(json.dumps(dict(utc=utc(), **values)), flush=True)


def write_json(path, value, *, initial=False):
    text = json.dumps(value, indent=2) + '\n'
    if initial:
        with path.open('x', encoding='utf-8') as output:
            output.write(text)
        return
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8') as output:
        output.write(text)
    os.replace(temporary, path)  # Update only this run's newly created files.


def check_health(receipt, serial, expected, node=None):
    if receipt.get('schema') != 'ptp_scope_hardware_rpc_v1' or receipt.get('status') != 'ok':
        raise ValueError('Hardware RPC failed: ' + str(receipt.get('error', 'invalid receipt')))
    if receipt.get('health_scope') != 'connected_boards_only':
        raise ValueError('Unexpected hardware health scope')
    connected = receipt.get('expected_connected')
    if connected != expected or serial not in connected:
        raise ValueError('Expected USB membership changed or selected board is not connected')
    cards = receipt.get('cards')
    if not isinstance(cards, list) or len(cards) != 3:
        raise ValueError('Incomplete card status inventory')
    inventory = {card.get('serial'): card for card in cards}
    if set(inventory) != {item[0] for item in BOARDS.values()}:
        raise ValueError('Card status serial inventory mismatch')
    for card in cards:
        if type(card.get('available')) is not bool:
            raise ValueError('Missing explicit card availability')
        if card['available']:
            if card.get('nominal') is not True:
                raise ValueError('Available card is not nominal: ' + card['serial'])
        elif card.get('nominal') is not None:
            raise ValueError('Unavailable card must have unknown health')
    if any(not inventory[item]['available'] for item in expected):
        raise ValueError('An expected connected card is unavailable')
    if node is not None:
        selected = inventory[serial]
        observer = int(selected['observer_hex'], 16)
        if (observer & 0x3ffff) != (node | 1 << 16) or \
           int(selected['output8_hex'], 16) != node or \
           int(selected['output9_hex'], 16) != 0 or int(selected['output10_hex'], 16) != 1:
            raise ValueError('Observed module is not the requested enabled selection')


def rpc(report, command, ready_hash, *, timeout=60):
    directory = report / 'hardware_rpc'
    ready = directory / 'ready.json'
    if hashlib.sha256(ready.read_bytes()).hexdigest() != ready_hash:
        raise RuntimeError('Hardware worker changed during campaign')
    request_id = 'campaign_' + uuid.uuid4().hex
    request = request_id + ' ' + command
    pending = directory / 'request.txt'
    temporary = directory / (request_id + '.tmp')
    if pending.exists():
        raise FileExistsError('A hardware RPC request is already pending')
    try:
        with temporary.open('x', encoding='ascii', newline='\n') as output:
            output.write(request + '\n')
        # Publish a closed file atomically, refusing to replace a pending request.
        os.link(temporary, pending)
    finally:
        temporary.unlink(missing_ok=True)
    path = directory / (request_id + '.json')
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f'Hardware RPC timed out; do not replay automatically: {request}')
        time.sleep(.1)
    receipt = json.loads(path.read_text(encoding='utf-8'))
    if receipt.get('request_id') != request_id or receipt.get('request') != request:
        raise ValueError('Hardware RPC request/receipt identity mismatch')
    if hashlib.sha256(ready.read_bytes()).hexdigest() != ready_hash:
        raise RuntimeError('Hardware worker changed during RPC')
    return path, receipt


def campaign(args):
    report = args.report.resolve()
    serial, first = BOARDS[args.board]
    if args.nodes is None:
        nodes = list(range(first, first + 3))
    else:
        if not re.fullmatch(r'[0-8](,[0-8])*', args.nodes):
            raise ValueError('--nodes must be comma-separated zero-based global IDs')
        nodes = [int(value) for value in args.nodes.split(',')]
    if len(set(nodes)) != len(nodes) or any(node not in range(first, first + 3) for node in nodes):
        raise ValueError('Nodes must be distinct and belong to the selected board')
    if args.count < 1 or not math.isfinite(args.window) or args.window <= 0:
        raise ValueError('Count and statistics-window seconds must be positive')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,31}', args.prefix or args.board):
        raise ValueError('Invalid group-log prefix')
    for node in nodes:
        if (report / FOLDERS[node]).exists():
            raise FileExistsError('Capture directory already exists: ' + str(report / FOLDERS[node]))
    evidence = None
    if args.verification_source:
        if not args.wiring_verified:
            raise ValueError('--verification-source requires --wiring-verified')
        source = args.verification_source
        if not source.is_absolute():
            source = report / source
        evidence = dict(file=os.path.relpath(source.resolve(), report).replace('\\', '/'),
                        sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    ready_path = report / 'hardware_rpc' / 'ready.json'
    ready_bytes = ready_path.read_bytes()
    ready = json.loads(ready_bytes)
    expected = ready.get('expected_connected')
    if ready.get('status') != 'ready' or not isinstance(expected, list) or len(expected) != 2 or \
       len(set(expected)) != 2 or 'OBS001A' not in expected or serial not in expected or \
       any(item not in {b[0] for b in BOARDS.values()} for item in expected):
        raise ValueError('Worker is not ready for the selected pair of boards')
    ready_hash = hashlib.sha256(ready_bytes).hexdigest()
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '_' + uuid.uuid4().hex[:8]
    log_path = report / f'group_run_{args.prefix or args.board}_{run_id}.json'
    log = dict(schema='ptp_scope_group_run_v1', status='running', started_utc=utc(),
               board=args.board, nodes=nodes, count=args.count, window_seconds=args.window,
               expected_connected=expected, health_scope='connected_boards_only',
               worker_ready_sha256=ready_hash, wiring_verified=args.wiring_verified,
               wiring_verification_source=evidence, cases=[])
    write_json(log_path, log, initial=True)
    try:
        for node in nodes:
            case_id = f'{args.board}_M{node + 1}'
            output = report / FOLDERS[node]
            record = dict(id=case_id, directory=FOLDERS[node], status='running')
            log['cases'].append(record)
            write_json(log_path, log)
            emit(event='case_begin', case_id=case_id, directory=str(output))
            before_path, before = rpc(report, f'observe {serial} {node}', ready_hash)
            check_health(before, serial, expected, node)
            record['health_before_receipt'] = before_path.relative_to(report).as_posix()
            command = [sys.executable, str(CAPTURE), str(output),
                       '--case-id', case_id, '--label', case_id, '--board', args.board,
                       '--node', str(node), '--count', str(args.count), '--window', str(args.window)]
            capture_error = None
            try:
                subprocess.run(command, check=True, shell=False)
            except (OSError, subprocess.SubprocessError) as error:
                capture_error = error
                record['capture_error'] = str(error)
            after_path, after = rpc(report, 'status', ready_hash)
            record['health_after_receipt'] = after_path.relative_to(report).as_posix()
            case_path = output / 'case.json'
            if case_path.exists():
                case = json.loads(case_path.read_text(encoding='utf-8'))
                if (case.get('id'), case.get('board'), case.get('observer_node')) != (case_id, args.board, node):
                    raise ValueError('Collector case metadata differs from requested module')
                case.update(health_before_receipt=record['health_before_receipt'],
                            health_after_receipt=record['health_after_receipt'],
                            wiring_verified=args.wiring_verified,
                            wiring_verification_source='operator_cli_flag' if args.wiring_verified else 'unverified')
                if evidence is not None:
                    case['wiring_verification_evidence'] = evidence
                if case_id == 'A_M1':
                    case['path_identity_verified'] = args.wiring_verified
                write_json(case_path, case)
            check_health(after, serial, expected, node)
            if capture_error:
                raise RuntimeError(f'Capture failed for {case_id}: {capture_error}') from capture_error
            acquisition = json.loads((output / 'acquisition.json').read_text(encoding='utf-8'))
            if acquisition.get('status') != 'acquired' or acquisition.get('fresh_single_acquisitions') != args.count:
                raise ValueError('Collector did not complete the requested fresh acquisitions')
            record.update(status='acquired', finished_utc=utc())
            write_json(log_path, log)
            emit(event='case_end', case_id=case_id, status='acquired')
        log['status'] = 'acquired'
    except BaseException as error:
        log.update(status='failed', error=str(error))
        if log['cases']:
            log['cases'][-1].update(status='failed', error=str(error))
        raise
    finally:
        log['finished_utc'] = utc()
        write_json(log_path, log)
        emit(event='group_end', status=log['status'], log=str(log_path))
    return log_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--board', choices=tuple(BOARDS), required=True)
    parser.add_argument('--nodes', help='Comma-separated zero-based global IDs; default all three local nodes')
    parser.add_argument('--count', type=int, default=100)
    parser.add_argument('--window', type=float, default=20, help='Scope statistics window in seconds')
    parser.add_argument('--prefix', help='Unique group-log filename prefix; fixed case folder names are retained')
    parser.add_argument('--wiring-verified', action='store_true',
                        help='Operator confirms probe placement and OBS output identity; never inferred from health')
    parser.add_argument('--verification-source', type=Path,
                        help='Optional existing verification evidence file, relative to report directory')
    args = parser.parse_args()
    campaign(args)


if __name__ == '__main__':
    main()
