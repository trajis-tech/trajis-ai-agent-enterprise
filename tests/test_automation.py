import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from test_workspace_api import WorkspaceApiFixture
from backend import server
from backend.agent_app import dispatch_tool, queue_bundle_approval
from backend.automation_runtime import AutomationRuntime, broker_app
from starlette.testclient import TestClient

XAML = '<Activity xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities"><Sequence><WriteLine Text="Test" /></Sequence></Activity>'


class BundleTests(WorkspaceApiFixture):
    def test_bundle_approval_hash_covers_both_files(self):
        p = self.create('bundle')
        deps = server._make_deps(p, p['session_id'], 't1')
        result = json.loads(dispatch_tool(deps, 'write_automation_bundle', {'path': 'automation/demo.json', 'artifact': {'name': 'Demo', 'xaml': XAML}}))
        approval = queue_bundle_approval(deps, 'call', result['manifest'])
        workflow = Path(p['path']) / result['n8n_path']
        data = json.loads(workflow.read_text(encoding='utf-8')); data['name'] = 'changed'
        workflow.write_text(json.dumps(data), encoding='utf-8')
        response = self.client.post('/api/approve', headers=self.headers(p), json={'approval_id': approval, 'decision': 'approve'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.db.get_pending(approval)['status'], 'pending')

    def test_plan_cannot_prepare_or_approve_bundle(self):
        p = self.create('planbundle')
        self.db.set_mode(p['session_id'], 'plan')
        deps = server._make_deps(p, p['session_id'], 't')
        with self.assertRaises(PermissionError):
            dispatch_tool(deps, 'write_automation_bundle', {'path': 'x.json', 'artifact': {'name': 'x', 'xaml': XAML}})
        with self.assertRaises(PermissionError): queue_bundle_approval(deps, 'call', 'x.json')

    def test_switching_mode_revokes_pending_without_deleting_history(self):
        p = self.create('history')
        self.db.save_agent_history(p['session_id'], b'[]', [])
        self.db.append_message(p['session_id'], 'user', {'content': 'keep me'})
        self.db.set_mode(p['session_id'], 'ask')
        self.assertIsNotNone(self.db.agent_history(p['session_id']))
        self.assertEqual(self.db.messages(p['session_id'])[0]['payload']['content'], 'keep me')


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.runtime = AutomationRuntime(Path(self.tmp.name), Path(self.tmp.name) / 'missing')
        self.addCleanup(self.runtime.close)

    def test_disabled_deployment_and_cross_project_rejected(self):
        ident = self.runtime.register('project1', {'name': 'x', 'xaml': XAML})
        with self.assertRaises(PermissionError): self.runtime.submit(ident, {}, 'key')
        with self.assertRaises(ValueError): self.runtime.deployment(ident, 'project2')

    def test_idempotency_does_not_repeat_work(self):
        ident = self.runtime.register('project1', {'name': 'x', 'xaml': XAML}); self.runtime.enable(ident)
        with patch.object(self.runtime.pool, 'submit') as start:
            a = self.runtime.submit(ident, {'x': 1}, 'key')
            b = self.runtime.submit(ident, {'x': 1}, 'key')
            self.assertEqual(a['run_id'], b['run_id']); self.assertEqual(start.call_count, 1)
            with self.assertRaises(ValueError): self.runtime.submit(ident, {'x': 2}, 'key')
        with self.assertRaises(ValueError): self.runtime.get_run(a['run_id'], 'project2')

    def test_broker_requires_auth_and_rejects_browser_origin(self):
        with TestClient(broker_app(self.runtime)) as client:
            self.assertEqual(client.get('/v1/health').status_code, 401)
            headers = {'Authorization': 'Bearer ' + self.runtime.token, 'Host': '127.0.0.1:8771'}
            self.assertEqual(client.get('/v1/health', headers=headers).status_code, 200)
            self.assertEqual(client.get('/v1/health', headers={**headers, 'Origin': 'https://evil.invalid'}).status_code, 403)
