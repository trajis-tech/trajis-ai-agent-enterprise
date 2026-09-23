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

    def test_setup_archive_is_one_package(self):
        from pack_setup import pack_setup
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '一鍵安裝.bat').write_text('call build\\install_runtime.bat --online\n', encoding='utf-8')
            (root / 'app/config').mkdir(parents=True)
            (root / 'app/config/custom_api.json').write_text('{"apiKeyEncrypted":"SECRET"}', encoding='utf-8')
            (root / 'filesystem/.runtime').mkdir(parents=True)
            (root / 'filesystem/.runtime/state.db').write_text('SECRET', encoding='utf-8')
            sqlite = root / 'filesystem/system/knowledge/dependencies.sqlite'
            sqlite.parent.mkdir(parents=True)
            sqlite.write_bytes(b'sqlite')
            for rel in ('vendor/openrpa-runtime-1.4.57.13-win-x64.zip', 'vendor/n8n-runtime-2.34.6-win-x64.zip'):
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'PK')
            output = root / 'setup.zip'
            pack_setup(root, output)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertIn('一鍵安裝.bat', names)
                self.assertIn('vendor/openrpa-runtime-1.4.57.13-win-x64.zip', names)
                self.assertIn('vendor/n8n-runtime-2.34.6-win-x64.zip', names)
                self.assertIn('filesystem/system/knowledge/dependencies.sqlite', names)
                self.assertNotIn('filesystem/.runtime/state.db', names)
                self.assertEqual(json.loads(archive.read('app/config/custom_api.json'))['apiKeyEncrypted'], '')
