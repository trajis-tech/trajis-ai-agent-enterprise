from io import BytesIO
from pathlib import Path
import zipfile

from test_workspace_api import WorkspaceApiFixture


class FileApiTests(WorkspaceApiFixture):
    def test_import_download_export_and_undo(self):
        project = self.create('files')
        headers = self.headers(project)
        data = b'hello,world\n1,2\n'
        response = self.client.post('/api/files/import?path=sample.csv', headers=headers, content=data)
        self.assertEqual(response.status_code, 200)
        turn_id = response.json()['turn_id']
        self.assertEqual(self.client.get('/api/files/download?path=sample.csv', headers=headers).content, data)
        archive = self.client.get('/api/files/export', headers=headers)
        with zipfile.ZipFile(BytesIO(archive.content)) as z:
            self.assertEqual(z.read('sample.csv'), data)
        undone = self.client.post('/api/undo', headers=headers, json={'turn_id': turn_id})
        self.assertEqual(undone.json()['restored'], ['sample.csv'])
        self.assertFalse((Path(project['path']) / 'sample.csv').exists())

    def test_import_rejects_overwrite_and_forbidden_names(self):
        project = self.create('files')
        headers = self.headers(project)
        self.assertEqual(self.client.post('/api/files/import?path=README.md', headers=headers, content=b'bad').status_code, 409)
        for path in ('.env', 'secret.pem', '../escape.txt', 'test.txt:secret'):
            self.assertEqual(self.client.post('/api/files/import', params={'path': path}, headers=headers, content=b'bad').status_code, 403)

    def test_binary_preview_and_secret_filter(self):
        project = self.create('files')
        root = Path(project['path'])
        (root / '.env').write_text('secret')
        (root / 'image.png').write_bytes(b'\x89PNG\x00\x01')
        headers = self.headers(project)
        result = self.client.get('/api/file?path=image.png', headers=headers).json()
        self.assertTrue(result['binary'])
        self.assertEqual(result['content'], '')
        listing = self.client.get('/api/files', headers=headers).json()
        self.assertNotIn('.env', [f['path'] for f in listing['files']])
        with zipfile.ZipFile(BytesIO(self.client.get('/api/files/export', headers=headers).content)) as z:
            self.assertNotIn('.env', z.namelist())
