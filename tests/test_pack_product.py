from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build'))
from pack_product import pack


class PackagePrivacyTests(unittest.TestCase):
    def test_excludes_projects_runtime_and_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {'app/config/custom_api.json': '{"apiKeyEncrypted":"SECRET"}',
                     'app/config/custom_api.local.json': 'SECRET',
                     'app/frontend/app.js': 'code',
                     'filesystem/projects/Ab3K9-demo/secret.txt': 'SECRET',
                     'filesystem/.runtime/state.db': 'SECRET',
                     'tests/ui-test-sample/gateway.json': 'SECRET'}
            for name, value in files.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(value)
            output = root / 'bundle.zip'
            pack(root, output)
            with zipfile.ZipFile(output) as archive:
                self.assertIn('app/frontend/app.js', archive.namelist())
                self.assertNotIn('filesystem/projects/Ab3K9-demo/secret.txt', archive.namelist())
                self.assertTrue(all(b'SECRET' not in archive.read(name) for name in archive.namelist()))
                self.assertEqual(json.loads(archive.read('app/config/custom_api.json'))['apiKeyEncrypted'], '')
