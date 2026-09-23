from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from backend.state import StateDB


class StateTests(unittest.TestCase):
    def test_append_only_messages(self) -> None:
        path = Path(tempfile.mkdtemp()) / "state.db"
        db = StateDB(path)
        db.ensure_session("s1", "Ab3K9")
        db.append_message("s1", "user", {"content": "hi"})
        db.append_message("s1", "assistant", {"content": "ok"})
        msgs = db.messages("s1")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["payload"]["content"], "hi")


if __name__ == "__main__":
    unittest.main()
