"""Read historical reports from the verified archive catalogue on demand.

Importing this module never opens archives or creates files. Extracted evidence
is an ignored cache, not a second set of reports to commit.
"""
from pathlib import Path, PurePosixPath
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
_ARCHIVE_TOOL = Path(__file__).resolve().parents[1] / 'scripts/report_archive.py'


def _digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _extract_archive(archive, output):
    # CLI callers may have only tools/ on sys.path. Load the sibling tool
    # lazily without changing the caller's import search path.
    name = '_obsidian_report_archive'
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, _ARCHIVE_TOOL)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    module.extract(archive, output)


def resolve_report_path(relative):
    """Return an existing path or restore its catalogue archive into build/.

    Catalogue members retain their original repository-relative paths. A bad
    archive checksum is rejected even when an older extracted cache exists.
    Existing caller-provided files/directories take precedence.
    """
    path = Path(relative)
    candidate = (path if path.is_absolute() else ROOT / path).resolve()
    if candidate.exists():
        return candidate
    try:
        original = candidate.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        raise FileNotFoundError(candidate) from None
    catalog_path = ROOT / 'reports/data/catalog.json'
    if not catalog_path.exists():
        catalog_path = ROOT / 'reports/catalog.json'
    if not catalog_path.exists():
        raise FileNotFoundError(candidate)
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    if catalog.get('schema') != 'obsidian_reports_catalog_v1':
        raise ValueError('Unsupported report catalogue schema')
    matches = []
    for entry in catalog.get('archives', []):
        for root in entry.get('original_roots', []):
            parts = PurePosixPath(root)
            if parts.is_absolute() or '..' in parts.parts or '\\' in root:
                raise ValueError('Unsafe original report root in catalogue')
            if original == root or original.startswith(root.rstrip('/') + '/'):
                matches.append((len(root), entry))
    if not matches:
        raise FileNotFoundError(candidate)
    matches.sort(key=lambda value: value[0], reverse=True)
    if len(matches) > 1 and matches[0][0] == matches[1][0]:
        raise ValueError('Ambiguous report catalogue roots: ' + original)
    entry = matches[0][1]
    identifier, filename, expected = entry['id'], entry['file'], entry['sha256'].lower()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', identifier) or \
       filename in ('', '.', '..') or PurePosixPath(filename).name != filename or '\\' in filename or ':' in filename:
        raise ValueError('Unsafe archive ID or filename in report catalogue')
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('Invalid archive checksum in report catalogue')
    archive = (catalog_path.parent / filename).resolve()
    if archive.parent != catalog_path.parent.resolve():
        raise ValueError('Archive escaped its catalogue directory')
    if _digest(archive) != expected:
        raise ValueError('Report archive SHA256 mismatch: ' + str(archive))
    cache_root = (ROOT / 'build/report_cache').resolve()
    cache = cache_root / identifier
    restored = cache / original
    marker = cache / '.archive_sha256'
    if cache.exists():
        if not marker.is_file() or marker.read_text(encoding='ascii').strip() != expected:
            raise ValueError('Stale or incomplete generated report cache: ' + str(cache))
        if not restored.exists():
            raise FileNotFoundError(restored)
        return restored
    cache_root.mkdir(parents=True, exist_ok=True)
    temporary = cache_root / ('.' + identifier + '.' + uuid.uuid4().hex)
    try:
        _extract_archive(archive, temporary)
        (temporary / '.archive_sha256').write_text(expected + '\n', encoding='ascii')
        try:
            temporary.rename(cache)
        except FileExistsError:
            if not marker.is_file() or marker.read_text(encoding='ascii').strip() != expected:
                raise ValueError('Conflicting generated report cache: ' + str(cache)) from None
    finally:
        if temporary.exists():
            # This unique directory is created only by the extraction above.
            if temporary.resolve().parent != cache_root or not temporary.name.startswith('.' + identifier + '.'):
                raise ValueError('Temporary report cache escaped its intended directory')
            shutil.rmtree(temporary)
    if not restored.exists():
        raise FileNotFoundError(restored)
    return restored
