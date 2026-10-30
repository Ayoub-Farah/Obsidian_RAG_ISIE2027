"""Pack verified report evidence and restore its original repository-relative paths.

Archives retain exact file bytes, including excluded measurements and diagnostics.
Packing never deletes sources. Extraction validates every member before writing
and refuses to replace an existing file with different content.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import stat
import uuid
import zipfile


SCHEMA = 'obsidian_report_archive_v1'
MANIFEST = 'MANIFEST.json'
CHUNK = 1024 * 1024


def _safe_name(name):
    if not isinstance(name, str) or not name or '\\' in name or name.startswith('/') or PureWindowsPath(name).drive:
        raise ValueError(f'Unsafe archive path: {name!r}')
    parts = name.split('/')
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{prefix}{i}' for prefix in ('COM', 'LPT') for i in range(1, 10)}
    if any(part in ('', '.', '..') or ':' in part or part.endswith((' ', '.')) or
           any(ord(c) < 32 for c in part) or part.split('.')[0].upper() in reserved for part in parts):
        raise ValueError(f'Unsafe archive path: {name!r}')
    return name


def _no_links(path):
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError(f'Links and reparse points are not accepted: {item}')


def _snapshot(path):
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _digest(stream):
    value = hashlib.sha256()
    size = 0
    for block in iter(lambda: stream.read(CHUNK), b''):
        value.update(block)
        size += len(block)
    return size, value.hexdigest()


def _file_digest(path):
    with path.open('rb') as stream:
        return _digest(stream)


def _collect(root, sources):
    found = {}
    names = set()

    def visit(path):
        _no_links(path)
        if path.is_dir():
            for child in sorted(path.iterdir()):
                visit(child)
        elif path.is_file():
            name = _safe_name(path.relative_to(root).as_posix())
            if name.casefold() == MANIFEST.casefold() or name.casefold() in names:
                raise ValueError(f'Duplicate or reserved archive path: {name}')
            names.add(name.casefold())
            found[name] = (path, _snapshot(path))
        else:
            raise ValueError(f'Expected a regular source file or directory: {path}')

    for source in sources:
        visit(source)
    if not found:
        raise ValueError('No files selected for the archive')
    return dict(sorted(found.items()))


def _inspect(archive):
    infos = archive.infolist()
    names = [info.filename for info in infos]
    folded = set()
    for info in infos:
        name = _safe_name(info.filename)
        mode = (info.external_attr >> 16) & 0xffff
        if info.is_dir() or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG):
            raise ValueError(f'Archive contains a non-regular member: {name}')
        if name.casefold() in folded:
            raise ValueError(f'Duplicate case-insensitive archive path: {name}')
        folded.add(name.casefold())
        if info.flag_bits & 1:
            raise ValueError('Encrypted report members are not supported')
    for name in names:
        parts = name.casefold().split('/')
        if any('/'.join(parts[:i]) in folded for i in range(1, len(parts))):
            raise ValueError(f'Archive file/directory collision: {name}')
    if names.count(MANIFEST) != 1:
        raise ValueError('Exactly one MANIFEST.json is required')
    try:
        manifest = json.loads(archive.read(MANIFEST).decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid archive manifest') from error
    if not isinstance(manifest, dict) or manifest.get('schema') != SCHEMA or not isinstance(manifest.get('files'), list):
        raise ValueError('Unsupported archive manifest schema')
    expected = {}
    folded = set()
    for entry in manifest['files']:
        if not isinstance(entry, dict):
            raise ValueError('Invalid manifest member')
        name = _safe_name(entry.get('path'))
        if name.casefold() == MANIFEST.casefold() or name.casefold() in folded:
            raise ValueError(f'Duplicate or reserved manifest path: {name}')
        folded.add(name.casefold())
        size, digest = entry.get('size'), entry.get('sha256')
        if type(size) is not int or size < 0 or not isinstance(digest, str) or len(digest) != 64 or \
           any(c not in '0123456789abcdef' for c in digest):
            raise ValueError(f'Invalid manifest size or SHA256: {name}')
        expected[name] = entry
    if not expected or set(names) != set(expected) | {MANIFEST}:
        raise ValueError('Archive member inventory differs from manifest')
    if manifest.get('file_count') != len(expected) or manifest.get('total_bytes') != sum(item['size'] for item in expected.values()):
        raise ValueError('Manifest totals differ from its member inventory')
    for name, entry in expected.items():
        if archive.getinfo(name).file_size != entry['size']:
            raise ValueError(f'Archive size mismatch: {name}')
        with archive.open(name) as source:
            size, digest = _digest(source)
        if size != entry['size'] or digest != entry['sha256']:
            raise ValueError(f'Archive SHA256 mismatch: {name}')
    return manifest


def verify(archive: Path) -> dict:
    archive = Path(archive).absolute()
    _no_links(archive)
    before = _snapshot(archive)
    try:
        with zipfile.ZipFile(archive, 'r') as source:
            manifest = _inspect(source)
        size, digest = _file_digest(archive)
    except (zipfile.BadZipFile, RuntimeError, EOFError) as error:
        raise ValueError(f'Invalid report archive: {archive}') from error
    if _snapshot(archive) != before:
        raise ValueError('Archive changed during verification')
    return dict(archive=str(archive.resolve()), sha256=digest, archive_bytes=size,
                member_count=manifest['file_count'], payload_bytes=manifest['total_bytes'], manifest=manifest)


def pack(root: Path, paths: list[Path], output: Path) -> dict:
    root = Path(root).absolute()
    _no_links(root)
    root = root.resolve(strict=True)
    if not root.is_dir() or not paths:
        raise ValueError('Root must be a directory and at least one source is required')
    sources = []
    for value in paths:
        path = Path(value)
        path = path if path.is_absolute() else root / path
        _no_links(path)
        path = path.resolve(strict=True)
        if not path.is_relative_to(root) or path == root:
            raise ValueError(f'Source must be strictly inside the repository root: {path}')
        sources.append(path)
    output = Path(output).absolute()
    _no_links(output)
    output = output.resolve()
    if any(output == source or source.is_dir() and output.is_relative_to(source) for source in sources):
        raise ValueError('Output archive cannot be inside a selected source')
    if output.exists():
        raise FileExistsError(output)
    selected = _collect(root, sources)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name('.' + output.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        entries = []
        with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as target:
            for name, (path, initial) in selected.items():
                _no_links(path)
                if _snapshot(path) != initial:
                    raise ValueError(f'Source changed before packing: {path}')
                digest, size = hashlib.sha256(), 0
                with path.open('rb') as source, target.open(name, 'w', force_zip64=True) as member:
                    for block in iter(lambda: source.read(CHUNK), b''):
                        member.write(block)
                        digest.update(block)
                        size += len(block)
                if _snapshot(path) != initial or size != initial[2]:
                    raise ValueError(f'Source changed during packing: {path}')
                entries.append(dict(path=name, size=size, sha256=digest.hexdigest()))
            manifest = dict(schema=SCHEMA, layout='repository-relative',
                            created_utc=datetime.now(timezone.utc).isoformat(),
                            file_count=len(entries), total_bytes=sum(item['size'] for item in entries), files=entries)
            target.writestr(MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
        # Re-walk to detect files added, removed or changed while copying.
        if _collect(root, sources) != selected:
            raise ValueError('Source tree changed during packing')
        result = verify(temporary)
        # The hard-link publication is atomic and refuses an existing output.
        os.link(temporary, output)
        result['archive'] = str(output)
        return result
    finally:
        temporary.unlink(missing_ok=True)


def extract(archive: Path, output: Path) -> Path:
    archive = Path(archive).absolute()
    _no_links(archive)
    before = _snapshot(archive)
    output = Path(output).absolute()
    _no_links(output)
    output = output.resolve()
    try:
        with zipfile.ZipFile(archive, 'r') as source:
            manifest = _inspect(source)
            targets = []
            # Preflight every collision before restoring any payload.
            for entry in manifest['files']:
                target = output.joinpath(*entry['path'].split('/'))
                _no_links(target)
                if not target.resolve().is_relative_to(output):
                    raise ValueError(f'Extraction escapes the output directory: {entry["path"]}')
                for parent in target.parents:
                    if parent == output.parent:
                        break
                    if parent.exists() and not parent.is_dir():
                        raise ValueError(f'Extraction directory is an existing file: {parent}')
                if target.exists() and (not target.is_file() or _file_digest(target) != (entry['size'], entry['sha256'])):
                    raise ValueError(f'Extraction would overwrite different content: {target}')
                targets.append((entry, target))
            for entry, target in targets:
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                _no_links(target)
                temporary = target.with_name('.' + target.name + '.' + uuid.uuid4().hex + '.tmp')
                try:
                    digest, size = hashlib.sha256(), 0
                    with source.open(entry['path']) as member, temporary.open('xb') as destination:
                        for block in iter(lambda: member.read(CHUNK), b''):
                            destination.write(block)
                            digest.update(block)
                            size += len(block)
                    if (size, digest.hexdigest()) != (entry['size'], entry['sha256']):
                        raise ValueError(f'Member changed during extraction: {entry["path"]}')
                    os.link(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
    except (zipfile.BadZipFile, RuntimeError, EOFError) as error:
        raise ValueError(f'Invalid report archive: {archive}') from error
    if _snapshot(archive) != before:
        raise ValueError('Archive changed during extraction')
    output.mkdir(parents=True, exist_ok=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    packing = commands.add_parser('pack')
    packing.add_argument('archive', type=Path)
    packing.add_argument('--root', type=Path, default=Path.cwd())
    packing.add_argument('--paths', type=Path, nargs='+', required=True)
    checking = commands.add_parser('verify')
    checking.add_argument('archive', type=Path)
    extraction = commands.add_parser('extract')
    extraction.add_argument('archive', type=Path)
    extraction.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'pack':
        result = pack(args.root, args.paths, args.archive)
    elif args.command == 'verify':
        result = verify(args.archive)
    else:
        result = dict(output=str(extract(args.archive, args.output)))
    if 'manifest' in result:
        result = {key: value for key, value in result.items() if key != 'manifest'}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
