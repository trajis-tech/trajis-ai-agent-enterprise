import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'build'))
import deployment_assets as assets
import install_from_lock as installer


class DeploymentTests(unittest.TestCase):
    def test_inventory_matches_every_pinned_asset(self):
        lock = json.loads((ROOT / 'build.lock.json').read_text(encoding='utf-8'))
        rows = assets.inventory(lock)
        self.assertEqual(len(rows), 5 + len(lock['wheels']))
        self.assertEqual(len({r['path'] for r in rows}), len(rows))
        self.assertTrue(any(r['component'] == 'openrpa_runtime' for r in rows))

    def test_missing_and_corrupt_assets_reported_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'bad.zip').write_bytes(b'corrupt')
            rows = [{'path': 'bad.zip', 'sha256': '0' * 64}, {'path': 'absent.zip', 'sha256': '0' * 64}]
            with patch.object(assets.urllib.request, 'urlopen', side_effect=AssertionError('network forbidden')):
                errors = assets.problems(root, rows)
            self.assertEqual(errors, ['HASH MISMATCH: bad.zip', 'MISSING: absent.zip'])

    def test_offline_download_guard(self):
        with patch.object(installer, 'OFFLINE', True), patch.object(installer.urllib.request, 'urlopen') as network:
            with self.assertRaisesRegex(SystemExit, 'Offline mode forbids'):
                installer.download('https://example.invalid', Path('never-created.zip'))
            network.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'CMD is Windows-only')
    def test_cmd_offline_missing_and_wrong_hash(self):
        with tempfile.TemporaryDirectory(prefix='cmd install ! ') as folder:
            root = Path(folder)
            (root / 'build').mkdir()
            shutil.copyfile(ROOT / 'build/install_runtime.bat', root / 'build/install_runtime.bat')
            (root / 'build.lock.json').write_text('{}')
            cmd = [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', 'build\\install_runtime.bat', '--offline']
            result = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('No download attempted', result.stdout)
            cache = root / 'vendor/wheels'
            cache.mkdir(parents=True)
            archive = cache / 'python-3.11.9-embed-amd64.zip'
            archive.write_bytes(b'corrupt')
            result = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('SHA-256 mismatch', result.stdout)
            self.assertEqual(archive.read_bytes(), b'corrupt')
            self.assertFalse((root / 'portable_python').exists())


if __name__ == '__main__':
    unittest.main()
