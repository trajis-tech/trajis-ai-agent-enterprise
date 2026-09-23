from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from backend.hitl import reject_client_overrides
from backend.state import StateDB


class HitlTests(unittest.TestCase):
    def test_rejects_forged_history(self) -> None:
        self.assertIsNotNone(reject_client_overrides({"approval_id": "x", "message_history": []}))
        self.assertIsNotNone(reject_client_overrides({"approval_id": "x", "args": {"path": "x"}}))
        self.assertIsNotNone(reject_client_overrides({"approval_id": "x", "deferred_tool_results": {}}))

    def test_allows_id_and_decision_only(self) -> None:
        self.assertIsNone(reject_client_overrides({"approval_id": "x", "decision": "approve"}))

    def test_pending_record_has_no_client_history(self) -> None:
        db = StateDB(Path(tempfile.mkdtemp()) / "state.db")
        approval = db.put_pending(
            {
                "session_id": "s1",
                "project_id": "Ab3K9",
                "tool_call_id": "c1",
                "tool_name": "publish_workflow",
                "args_hash": "abc",
                "args": {"path": "n8n/workflows/demo.json"},
                "expires_at": "2099-01-01T00:00:00+00:00",
            }
        )
        rec = db.get_pending(approval)
        self.assertEqual(rec["tool_name"], "publish_workflow")
        self.assertNotIn("message_history", rec)
        self.assertEqual(rec["args"]["path"], "n8n/workflows/demo.json")
