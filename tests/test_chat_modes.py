import json
from pathlib import Path
from test_workspace_api import WorkspaceApiFixture
from backend import server
from backend.agent_app import dispatch_tool, queue_publish_approval, build_pydantic_agent


class ChatModeTests(WorkspaceApiFixture):
    def test_modes_survive_reopen_and_deny_mutation(self):
        p = self.create('modes')
        h = self.headers(p)
        for mode in ('plan', 'ask'):
            r = self.client.post('/api/mode', headers=h, json={'mode': mode})
            self.assertEqual(r.status_code, 200)
            reopened = self.client.post('/api/projects/open', json={'folder': p['folder']}).json()
            self.assertEqual(self.client.get('/api/mode', headers=self.headers(reopened)).json()['mode'], mode)
            deps = server._make_deps(p, p['session_id'], 'test')
            for name, args in [('write_file', {'path': 'bad.txt', 'content': 'bad'}),
                               ('run_python', {'script_path': 'bad.py'}),
                               ('publish_workflow', {'path': 'bad.json'}),
                               ('delete_file', {'path': 'bad.txt'})]:
                with self.assertRaises(PermissionError):
                    dispatch_tool(deps, name, args, approved=True)
            with self.assertRaises(PermissionError):
                queue_publish_approval(deps, 'call', 'bad.json')
            self.assertEqual(self.client.post('/api/undo', headers=h, json={'turn_id': 't1'}).status_code, 403)
            self.assertEqual(self.client.post('/api/n8n', headers=h, json={'action': 'start'}).status_code, 403)
            self.assertFalse((Path(p['path']) / 'bad.txt').exists())

    def test_plan_is_server_record_and_ask_cannot_save(self):
        p = self.create('plan')
        self.db.set_mode(p['session_id'], 'plan')
        deps = server._make_deps(p, p['session_id'], 'test')
        before = sorted(str(x) for x in Path(p['path']).rglob('*'))
        saved = json.loads(dispatch_tool(deps, 'save_plan', {'content': '1. Inspect\n2. Validate'}))
        self.assertTrue(saved['plan_id'])
        self.assertEqual(sorted(str(x) for x in Path(p['path']).rglob('*')), before)
        self.db.set_mode(p['session_id'], 'ask')
        deps = server._make_deps(p, p['session_id'], 'test')
        with self.assertRaises(PermissionError):
            dispatch_tool(deps, 'save_plan', {'content': 'no'})

    def test_ask_can_inspect_environment_and_missing_knowledge(self):
        p = self.create('askenv')
        self.db.set_mode(p['session_id'], 'ask')
        deps = server._make_deps(p, p['session_id'], 't')
        env = json.loads(dispatch_tool(deps, 'inspect_automation_environment', {}))
        self.assertEqual(env['broker'], '127.0.0.1:8771')
        self.assertTrue(any('不是 OpenRPA 官方 REST' in note for note in env['notices']))
        docs = json.loads(dispatch_tool(deps, 'search_dependency_docs', {'query': 'OpenRPA'}))
        self.assertFalse(docs['available'])
        self.assertEqual(docs['results'], [])

    def test_mode_cannot_change_while_project_running(self):
        p = self.create('busy')
        server.LOCKS.acquire(p['id'], 'active')
        self.assertEqual(self.client.post('/api/mode', headers=self.headers(p), json={'mode': 'ask'}).status_code, 409)
        self.assertEqual(self.db.mode_state(p['session_id'])['mode'], 'general')

    def test_stale_turn_cannot_mutate_after_switching_back(self):
        p = self.create('epoch')
        old = server._make_deps(p, p['session_id'], 'old')
        self.db.set_mode(p['session_id'], 'ask')
        self.db.set_mode(p['session_id'], 'general')
        with self.assertRaises(PermissionError):
            dispatch_tool(old, 'write_file', {'path': 'x.txt', 'content': 'stale'})

    def test_model_only_receives_mode_tools(self):
        from pydantic_ai.models.test import TestModel
        for mode in ('plan', 'ask'):
            p = self.create(mode)
            self.db.set_mode(p['session_id'], mode)
            model = TestModel(call_tools=[])
            agent = build_pydantic_agent(model, mode=mode)
            agent.run_sync('inspect', deps=server._make_deps(p, p['session_id'], 't'))
            names = {t.name for t in model.last_model_request_parameters.function_tools}
            self.assertIn('read_file', names)
            self.assertNotIn('write_file', names)
            self.assertNotIn('publish_workflow', names)
            self.assertIn('inspect_automation_environment', names)
            self.assertIn('search_dependency_docs', names)
            self.assertNotIn('write_automation_bundle', names)
            self.assertEqual('save_plan' in names, mode == 'plan')
