import asyncio
import json
import unittest
from unittest.mock import patch

from test_function_model import _deps
from backend import server
from backend.agent_app import build_pydantic_agent
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart


class ModelRuntimeTests(unittest.TestCase):
    def test_canonical_history_and_deferred_result_resume(self):
        deps = _deps()
        self.addCleanup(deps.db.close)
        deps.db.ensure_session(deps.session_id, deps.project_id)
        (deps.project_root / "workflow.json").write_text("{}", encoding="utf-8")
        observed = []

        def respond(messages, info):
            observed.append(messages)
            returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
            if returns:
                return ModelResponse(parts=[TextPart('發佈完成，繼續整理報告。')])
            return ModelResponse(parts=[ToolCallPart('publish_workflow', '{"path":"workflow.json"}', 'publish-1')])

        agent = build_pydantic_agent(FunctionModel(respond))
        cfg = {'apiKeyEncrypted': 'test-only', 'requestUrl': 'https://example.invalid/v1', 'defaults': {'model': 'test'}}
        with patch.object(server, '_load_custom_api', return_value=cfg), \
             patch('backend.agent_app.build_pydantic_agent', return_value=agent), \
             patch('pydantic_ai.models.ALLOW_MODEL_REQUESTS', False):
            bucket = []
            asyncio.run(server._run_agent(deps, '請發佈流程', bucket))
            self.assertEqual(bucket[0][0], 'approval')
            approval_id = bucket[0][1]['approval_id']
            deps.db.save_approval_outcome(approval_id, json.dumps({'action': 'CREATE', 'n8n_workflow_id': '123'}))
            deps.db.resolve_pending(approval_id, 'approve')
            with patch('backend.agent_app.dispatch_tool', side_effect=AssertionError('must not publish twice')):
                reply = asyncio.run(server._run_agent(deps, '', []))
            self.assertIn('發佈完成', reply)
            self.assertEqual(json.loads(deps.db.agent_history(deps.session_id)['pending_json']), [])
            self.assertGreater(len(observed[-1]), 1)

    def test_false_environment_flag_does_not_enable_gateway(self):
        deps = _deps()
        self.addCleanup(deps.db.close)
        with patch.object(server, '_load_custom_api', return_value={}), \
             patch.dict('os.environ', {'ALLOW_MODEL_REQUESTS': 'False'}), \
             patch('backend.agent_app.build_pydantic_agent', side_effect=AssertionError('no gateway configured')):
            reply = asyncio.run(server._run_agent(deps, 'hello', []))
        self.assertIn('未執行 AI 工作', reply)

    def test_base_url_keeps_v1(self):
        self.assertEqual(server._base_url('https://gateway.example/v1'), 'https://gateway.example/v1')
        self.assertEqual(server._base_url('https://gateway.example/v1/chat/completions'), 'https://gateway.example/v1')

    def test_preupgrade_conversation_is_preserved_for_model(self):
        deps = _deps()
        self.addCleanup(deps.db.close)
        deps.db.ensure_session(deps.session_id, deps.project_id)
        deps.db.append_message(deps.session_id, "user", {"content": "legacy-context-marker"})
        captured = []
        def respond(messages, info):
            captured.append(str(messages))
            return ModelResponse(parts=[TextPart("ok")])
        agent = build_pydantic_agent(FunctionModel(respond))
        cfg = {'apiKeyEncrypted': 'test-only', 'requestUrl': 'https://example.invalid/v1', 'defaults': {'model': 'test'}}
        with patch.object(server, '_load_custom_api', return_value=cfg), patch('backend.agent_app.build_pydantic_agent', return_value=agent):
            asyncio.run(server._run_agent(deps, "continue", []))
        self.assertIn("legacy-context-marker", captured[0])
