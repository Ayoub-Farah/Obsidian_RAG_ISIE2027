"""Evidence-archive integrity, portability and non-destructive restoration."""
import hashlib
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import report_archive as reports


class ReportArchives(unittest.TestCase):
    def source(self, root):
        directory = root / 'reports' / 'campaign'
        directory.mkdir(parents=True)
        payloads = {'bytes.npz': b'\x00\xff\n\r\n' * 31,
                    'metadata.json': '{"label":"horloge ±4 ppm"}\n'.encode('utf-8'),
                    'empty.txt': b''}
        for name, payload in payloads.items():
            (directory / name).write_bytes(payload)
        return directory, payloads

    def artificial(self, archive, entries):
        files = [dict(path=name, size=len(value), sha256=hashlib.sha256(value).hexdigest())
                 for name, value in entries]
        manifest = dict(schema=reports.SCHEMA, files=files, file_count=len(files),
                        total_bytes=sum(item['size'] for item in files))
        with zipfile.ZipFile(archive, 'w') as target:
            for name, value in entries:
                target.writestr(name, value)
            target.writestr(reports.MANIFEST, json.dumps(manifest))
        return archive

    def test_round_trip_preserves_exact_bytes_and_original_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, values = self.source(root)
            archive = root / 'data' / 'evidence.zip'
            packed = reports.pack(root, [source], archive)
            verified = reports.verify(archive)
            self.assertEqual(packed['sha256'], verified['sha256'])
            self.assertEqual(verified['member_count'], len(values))
            self.assertEqual(verified['payload_bytes'], sum(map(len, values.values())))
            output = reports.extract(archive, root / 'replay')
            self.assertEqual(reports.extract(archive, output), output)
            for name, payload in values.items():
                self.assertEqual((output / 'reports' / 'campaign' / name).read_bytes(), payload)
                self.assertEqual((source / name).read_bytes(), payload)

    def test_modified_payload_is_rejected_even_with_a_valid_zip_crc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _ = self.source(root)
            archive = root / 'good.zip'
            reports.pack(root, [source], archive)
            modified = root / 'modified.zip'
            with zipfile.ZipFile(archive) as good, zipfile.ZipFile(modified, 'w') as bad:
                for member in good.namelist():
                    payload = good.read(member)
                    if member.endswith('bytes.npz'):
                        payload = bytes([payload[0] ^ 1]) + payload[1:]
                    bad.writestr(member, payload)
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                reports.verify(modified)
            output = root / 'replay'
            with self.assertRaises(ValueError):
                reports.extract(modified, output)
            self.assertFalse(output.exists())

    def test_unsafe_paths_and_windows_collisions_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i, name in enumerate(('../escape', '/absolute', 'C:/drive', 'C:relative',
                                      'reports/../escape', 'reports\\escape', 'reports/a:b',
                                      'reports/file.', 'reports/NUL.txt')):
                with self.subTest(name=name):
                    archive = self.artificial(root / f'unsafe{i}.zip', [(name, b'x')])
                    with self.assertRaises(ValueError):
                        reports.extract(archive, root / 'replay')
            archive = self.artificial(root / 'collision.zip', [('reports/a.json', b'a'), ('reports/A.json', b'b')])
            with self.assertRaisesRegex(ValueError, 'case-insensitive'):
                reports.verify(archive)
            archive = self.artificial(root / 'ancestor_collision.zip', [('reports/a', b'a'), ('reports/A/b', b'b')])
            with self.assertRaisesRegex(ValueError, 'file/directory collision'):
                reports.extract(archive, root / 'replay')
            self.assertFalse((root / 'replay').exists())

    def test_zip_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = self.artificial(root / 'link.zip', [('reports/link', b'../../escape')])
            rebuilt = root / 'with_symlink.zip'
            with zipfile.ZipFile(archive) as source, zipfile.ZipFile(rebuilt, 'w') as target:
                for name in source.namelist():
                    info = zipfile.ZipInfo(name)
                    info.create_system = 3
                    info.external_attr = ((stat.S_IFLNK | 0o777) if name == 'reports/link' else (stat.S_IFREG | 0o644)) << 16
                    target.writestr(info, source.read(name))
            with self.assertRaisesRegex(ValueError, 'non-regular'):
                reports.extract(rebuilt, root / 'replay')

    def test_restore_preflights_conflicts_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = self.artificial(root / 'data.zip', [('reports/a.txt', b'new'), ('reports/z.txt', b'old')])
            output = root / 'replay'
            (output / 'reports').mkdir(parents=True)
            conflicting = output / 'reports' / 'z.txt'
            conflicting.write_bytes(b'keep this')
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                reports.extract(archive, output)
            self.assertEqual(conflicting.read_bytes(), b'keep this')
            self.assertFalse((output / 'reports' / 'a.txt').exists())

    def test_pack_rejects_overlaps_and_output_inside_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _ = self.source(root)
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                reports.pack(root, [source, source / 'bytes.npz'], root / 'duplicate.zip')
            with self.assertRaisesRegex(ValueError, 'inside a selected source'):
                reports.pack(root, [source], source / 'recursive.zip')
            self.assertFalse((root / 'duplicate.zip').exists())
            self.assertFalse((source / 'recursive.zip').exists())

    def test_changing_source_is_not_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _ = self.source(root)
            original_open = zipfile.ZipFile.open

            def change_during_copy(archive, name, mode='r', *args, **kwargs):
                member = original_open(archive, name, mode, *args, **kwargs)
                if mode == 'w' and name == 'reports/campaign/bytes.npz':
                    (source / 'bytes.npz').write_bytes(b'changed while packing')
                return member

            with patch.object(zipfile.ZipFile, 'open', new=change_during_copy):
                with self.assertRaisesRegex(ValueError, 'changed'):
                    reports.pack(root, [source], root / 'changing.zip')
            self.assertFalse((root / 'changing.zip').exists())
            self.assertFalse(list(root.glob('.*.tmp')))


if __name__ == '__main__':
    unittest.main()
