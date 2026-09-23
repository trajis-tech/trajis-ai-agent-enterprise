from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from starlette.testclient import TestClient
from backend import server
from backend.state import StateDB
from backend.snapshot import SnapshotStore, controlled_write
from backend.locks import ProjectLock
from backend.audit import AuditLog


class WorkspaceApiFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fs = self.root / 'filesystem'
        self.projects = self.fs / 'projects'
        self.projects.mkdir(parents=True)
        self.runtime = self.fs / '.runtime'
        self.db = StateDB(self.runtime / 'state.db')
        self.addCleanup(self.db.close)
        for name, value in {'DB': self.db, 'SNAPSHOTS': SnapshotStore(self.runtime / 'snapshots'),
                            'LOCKS': ProjectLock(self.runtime), 'AUDIT': AuditLog(self.runtime / 'audit.jsonl')}.items():
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, value in {'filesystem_root': self.fs, 'system_root': self.fs / 'system',
                            'projects_root': self.projects}.items():
            patcher = patch.object(server, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(server.app)
        self.addCleanup(self.client.close)

    def create(self, topic):
        result = self.client.post('/api/projects/create', json={'topic': topic})
        self.assertEqual(result.status_code, 200)
        return result.json()

    def headers(self, project):
        return {'X-Agent-Session': project['session_id']}



class WorkspaceApiTests(WorkspaceApiFixture):
    def test_tabs_keep_their_own_projects(self):
        a, b = self.create('alpha'), self.create('beta')
        (Path(a['path']) / 'a.txt').write_text('alpha')
        (Path(b['path']) / 'b.txt').write_text('beta')
        for project, filename in ((a, 'a.txt'), (b, 'b.txt')):
            response = self.client.get('/api/files', headers=self.headers(project))
            names = [x['path'] for x in response.json()['files']]
            self.assertIn(filename, names)
            self.assertNotIn('b.txt' if filename == 'a.txt' else 'a.txt', names)
        self.assertEqual(self.client.get('/api/files').status_code, 400)

    def test_reopen_restores_history_and_session(self):
        a = self.create('alpha')
        self.db.append_message(a['session_id'], 'user', {'content': 'remember'}, 't1')
        reopened = self.client.post('/api/projects/open', json={'folder': a['folder']}).json()
        self.assertEqual(reopened['session_id'], a['session_id'])
        history = self.client.get('/api/session', headers=self.headers(a)).json()
        self.assertEqual(history['messages'][0]['payload']['content'], 'remember')
        self.assertEqual(self.client.get('/api/session').json()['messages'], [])

    def test_busy_undo_preserves_active_lock(self):
        a = self.create('alpha')
        server.LOCKS.acquire(a['id'], 'running-turn')
        response = self.client.post('/api/undo', headers=self.headers(a), json={'turn_id': 't1'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual((server.LOCKS.root / (a['id'] + '.lock')).read_text(), 'running-turn')

    def test_invalid_undo_id_is_rejected(self):
        a = self.create('alpha')
        response = self.client.post('/api/undo', headers=self.headers(a), json={'turn_id': '../escape'})
        self.assertEqual(response.status_code, 400)

    def test_other_session_cannot_resolve_approval(self):
        a, b = self.create('alpha'), self.create('beta')
        approval = self.db.put_pending({'session_id': a['session_id'], 'project_id': a['id'],
            'tool_call_id': 'call', 'tool_name': 'publish_workflow', 'args_hash': 'hash',
            'args': {'path': 'workflow.json'}, 'expires_at': '2099-01-01T00:00:00+00:00'})
        response = self.client.post('/api/approve', headers=self.headers(b),
                                    json={'approval_id': approval, 'decision': 'deny'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.db.get_pending(approval)['status'], 'pending')

    def test_disconnected_chat_cancels_model_and_releases_lock(self):
        import asyncio
        from types import SimpleNamespace
        project = self.create('cancel')

        async def check():
            started = asyncio.Event()
            stopped = asyncio.Event()
            async def fake_agent(deps, message, bucket):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
            async def body():
                return {"message": "long running task"}
            request = SimpleNamespace(json=body, state=SimpleNamespace(workspace={
                "project": project, "session": project["session_id"]}))
            with patch.object(server, "_run_agent", side_effect=fake_agent):
                response = await server.api_chat(request)
                await anext(response.body_iterator)
                waiting = asyncio.create_task(anext(response.body_iterator))
                await asyncio.wait_for(started.wait(), 3)
                waiting.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await waiting
                self.assertTrue(stopped.is_set())
                self.assertFalse((server.LOCKS.root / (project["id"] + ".lock")).exists())
                self.assertIn("中止", self.db.messages(project["session_id"])[-1]["payload"]["content"])
        asyncio.run(check())
