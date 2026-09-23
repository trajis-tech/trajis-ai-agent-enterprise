from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from backend.audit import AuditLog


class AuditTests(unittest.TestCase):
    def test_append_only(self) -> None:
        path = Path(tempfile.mkdtemp()) / "audit.jsonl"
        log = AuditLog(path)
        log.write({"tool": "write_file", "result": "ok"})
        log.write({"tool": "run_python", "result": "ok"})
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("write_file", lines[0])
        log.write({"tool": "publish_workflow", "result": "CREATE"})
        self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 3)
