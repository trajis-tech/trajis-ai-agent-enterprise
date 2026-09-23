from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from backend.audit import AuditLog
from backend.jail import FilesystemJail, JailPolicy
from backend.job_object import JobLimits
from backend.snapshot import SnapshotStore
from backend.staging import run_in_staging


class StagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.fs = self.tmp / "filesystem"
        self.proj = self.fs / "projects" / "Ab3K9-demo"
        self.proj.mkdir(parents=True)
        (self.proj / "work.py").write_text(
            "from pathlib import Path\nPath('out.txt').write_text('hello', encoding='utf-8')\n",
            encoding="utf-8",
        )
        self.jail = FilesystemJail(self.fs, self.fs / "system", self.proj, JailPolicy(write_extensions={".py", ".txt"}))
        (self.fs / "system").mkdir(exist_ok=True)
        self.snap = SnapshotStore(self.tmp / "snaps")
        self.audit = AuditLog(self.tmp / "audit.jsonl")

    def test_commit_via_staging(self) -> None:
        py = Path(sys.executable)
        result = run_in_staging(
            interpreter=py,
            script_rel="work.py",
            args=[],
            project_root=self.proj,
            staging_root=self.tmp / "staging",
            jail=self.jail,
            snapshots=self.snap,
            project_id="Ab3K9",
            turn_id="t1",
            audit=self.audit,
            timeout=20,
            limits=JobLimits(),
            stdout_limit=1000,
            pythonhome=py.parent,
        )
        self.assertIsNone(result.violation)
        self.assertTrue((self.proj / "out.txt").exists())
        self.assertEqual((self.proj / "out.txt").read_text(encoding="utf-8"), "hello")
        self.assertTrue(any(item.endswith("out.txt") for item in result.committed))

    def test_undo_restores(self) -> None:
        self.test_commit_via_staging()
        restored = self.snap.restore_turn("Ab3K9", "t1", self.jail)
        self.assertIn("out.txt", restored)
        self.assertFalse((self.proj / "out.txt").exists())


if __name__ == "__main__":
    unittest.main()
