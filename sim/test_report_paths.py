"""Archive catalogue lookup, checksum rejection and extraction cache reuse."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import report_paths


class ReportPathsTests(unittest.TestCase):
    def fixture(self, root):
        data = root / 'reports/data'
        data.mkdir(parents=True)
        archive = data / 'scope.zip'
        archive.write_bytes(b'archived evidence')
        entry = dict(id='scope', file='scope.zip',
                     sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                     original_roots=['reports/old_scope'])
        (data / 'catalog.json').write_text(json.dumps(dict(
            schema='obsidian_reports_catalog_v1', archives=[entry])), encoding='utf-8')
        return archive, entry

    def test_existing_report_needs_no_catalogue_or_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'report.json').write_text('original')
            with patch.object(report_paths, 'ROOT', root), \
                 patch.object(report_paths, '_extract_archive') as extract:
                result = report_paths.resolve_report_path('report.json')
            self.assertEqual(result.read_text(), 'original')
            self.assertFalse((root / 'build').exists())
            extract.assert_not_called()

    def test_extract_once_reuse_then_reject_archive_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive, _ = self.fixture(root)

            def extract(source, output):
                path = output / 'reports/old_scope/result.json'
                path.parent.mkdir(parents=True)
                path.write_text('unchanged evidence')

            with patch.object(report_paths, 'ROOT', root), \
                 patch.object(report_paths, '_extract_archive', side_effect=extract) as loader:
                first = report_paths.resolve_report_path('reports/old_scope/result.json')
                second = report_paths.resolve_report_path('reports/old_scope/result.json')
                self.assertEqual(first, second)
                self.assertEqual(second.read_text(), 'unchanged evidence')
                self.assertEqual(loader.call_count, 1)
                archive.write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                    report_paths.resolve_report_path('reports/old_scope/result.json')

    def test_catalogue_cannot_escape_archive_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, entry = self.fixture(root)
            with patch.object(report_paths, 'ROOT', root), \
                 patch.object(report_paths, '_extract_archive') as loader:
                for filename in ('../../outside.zip', '..'):
                    with self.subTest(filename=filename):
                        entry['file'] = filename
                        (root / 'reports/data/catalog.json').write_text(json.dumps(dict(
                            schema='obsidian_reports_catalog_v1', archives=[entry])), encoding='utf-8')
                        with self.assertRaisesRegex(ValueError, 'Unsafe archive'):
                            report_paths.resolve_report_path('reports/old_scope/result.json')
            loader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
