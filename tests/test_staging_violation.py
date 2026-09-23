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


class StagingViolationTests(unittest.TestCase):
    def test_direct_project_write_aborts_commit(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        fs = tmp / "filesystem"
        proj = fs / "projects" / "Ab3K9-demo"
        proj.mkdir(parents=True)
        (fs / "system").mkdir()
        real = (proj / "victim.txt").resolve()
        script = (
            "from pathlib import Path\n"
            f"Path(r'{real}').write_text('pwned', encoding='utf-8')\n"
            "Path('staging_only.txt').write_text('nope', encoding='utf-8')\n"
        )
        (proj / "evil.py").write_text(script, encoding="utf-8")
        jail = FilesystemJail(fs, fs / "system", proj, JailPolicy(write_extensions={".py", ".txt"}))
        result = run_in_staging(
            interpreter=Path(sys.executable),
            script_rel="evil.py",
            args=[],
            project_root=proj,
            staging_root=tmp / "staging",
            jail=jail,
            snapshots=SnapshotStore(tmp / "snaps"),
            project_id="Ab3K9",
            turn_id="t-viol",
            audit=AuditLog(tmp / "audit.jsonl"),
            timeout=20,
            limits=JobLimits(),
            stdout_limit=1000,
            pythonhome=Path(sys.executable).parent,
        )
        self.assertEqual(result.violation, "REAL_PROJECT_MUTATED")
        self.assertEqual(result.committed, [])
        self.assertFalse((proj / "staging_only.txt").exists())
        self.assertFalse(real.exists())
