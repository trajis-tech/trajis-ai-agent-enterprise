from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from backend.history import model_view
from backend.policy import Policy


class HistoryTests(unittest.TestCase):
    def test_pending_is_not_summarized(self) -> None:
        policy = Policy(raw={}, keep_recent_turns=2, max_tool_output_chars=20)
        messages = [{"role": "user", "payload": {"content": f"m{i}"}} for i in range(20)]
        view = model_view(messages, policy, pending_active=True)
        self.assertEqual(len(view), 20)

    def test_old_turns_summarized_when_not_pending(self) -> None:
        policy = Policy(raw={}, keep_recent_turns=2, max_tool_output_chars=20)
        messages = [{"role": "user", "payload": {"content": f"m{i}"}} for i in range(20)]
        view = model_view(messages, policy, pending_active=False)
        self.assertLess(len(view), 20)
        self.assertEqual(view[2]["payload"]["kind"], "summary")
