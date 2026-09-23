import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from backend.automation_runtime import AutomationRuntime
from backend import server
from backend.agent_app import build_pydantic_agent
from test_function_model import _deps
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import ModelResponse, ToolCallPart, TextPart


class IntegrationRecoveryTests(unittest.TestCase):
    def test_already_queued_work_does_not_run_after_quarantine(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = AutomationRuntime(Path(tmp), Path(tmp) / 'binaries')
            try:
                ident = runtime.register('p1', {'name': 'test', 'xaml': 'test'})
                runtime.enable(ident)
                with patch.object(runtime.pool, 'submit'):
                    run = runtime.submit(ident, {}, 'once')
                runtime._pause()
                with patch.object(runtime, '_ensure_robot', side_effect=AssertionError('must not start robot')):
                    runtime._run(run['run_id'], runtime.deployment(ident), {})
                self.assertEqual(runtime.get_run(run['run_id'])['status'], 'blocked')
            finally:
                runtime.close()
            reopened = AutomationRuntime(Path(tmp), Path(tmp) / 'binaries')
            try:
                self.assertTrue(reopened.health()['quarantined'])
                with self.assertRaises(RuntimeError): reopened.submit(ident, {}, 'new')
                with patch.object(reopened, '_ipc', side_effect=RuntimeError('no robot')):
                    reopened.recover()
                self.assertFalse(reopened.health()['quarantined'])
                self.assertEqual(reopened.get_run(run['run_id'])['status'], 'blocked')
            finally:
                reopened.close()

    def test_interrupted_running_job_pauses_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = AutomationRuntime(Path(tmp), Path(tmp) / 'binaries')
            ident = runtime.register('p1', {'name': 'test'}); runtime.enable(ident)
            with patch.object(runtime.pool, 'submit'):
                run = runtime.submit(ident, {}, 'once')
            runtime._state(run['run_id'], 'running')
            runtime.close()
            reopened = AutomationRuntime(Path(tmp), Path(tmp) / 'binaries')
            try:
                self.assertTrue(reopened.quarantined)
                self.assertEqual(reopened.get_run(run['run_id'])['status'], 'interrupted')
            finally: reopened.close()

    def test_pending_publish_can_resume_denied_in_readonly_mode(self):
        deps = _deps(); self.addCleanup(deps.db.close)
        deps.db.ensure_session(deps.session_id, deps.project_id)
        (deps.project_root / 'workflow.json').write_text('{}')
        cfg = {'apiKeyEncrypted': 'test-only', 'requestUrl': 'https://example.invalid/v1', 'defaults': {'model': 'test'}}
        initial = build_pydantic_agent(FunctionModel(lambda messages, info: ModelResponse(parts=[ToolCallPart('publish_workflow', {'path': 'workflow.json'}, 'pub-1')])))
        with patch.object(server, '_load_custom_api', return_value=cfg), patch('backend.agent_app.build_pydantic_agent', return_value=initial):
            asyncio.run(server._run_agent(deps, 'publish', []))
        saved = deps.db.agent_history(deps.session_id)
        deps.db.set_mode(deps.session_id, 'ask')
        deps.chat_mode = 'ask'; deps.mode_epoch = deps.db.mode_state(deps.session_id)['epoch']
        def readonly(messages, info):
            self.assertNotIn('publish_workflow', [tool.name for tool in info.function_tools])
            return ModelResponse(parts=[TextPart('read-only answer')])
        agent = build_pydantic_agent(FunctionModel(readonly), mode='ask')
        with patch.object(server, '_load_custom_api', return_value=cfg), patch('backend.agent_app.build_pydantic_agent', return_value=agent), patch('backend.agent_app.dispatch_tool', side_effect=AssertionError('no mutation')):
            self.assertEqual(asyncio.run(server._run_agent(deps, 'explain instead', [])), 'read-only answer')
        self.assertIn('pub-1', saved['history_json'])
