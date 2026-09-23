from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ChatErrorContractTests(unittest.TestCase):
    def test_run_agent_does_not_fallback_to_heuristic_on_import_failure(self) -> None:
        text = (ROOT / "app" / "backend" / "server.py").read_text(encoding="utf-8")
        self.assertIn("def _pydantic_ai_import_error", text)
        self.assertIn("pydantic_ai 無法載入", text)
        self.assertIn('AUDIT.write({"tool": "agent_run", "result": "error"', text)
        self.assertNotIn('"result": "fallback"', text)
        nested = text.split("async def _run_agent", 1)[1].split("def _pydantic_ai_import_error", 1)[0]
        self.assertNotIn("return _heuristic_turn(deps, message, bucket)", nested.split("if not has_key", 1)[-1])
