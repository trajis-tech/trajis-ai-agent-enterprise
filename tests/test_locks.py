from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from backend.locks import ProjectLock, ProjectLockBusy


class LockTests(unittest.TestCase):
    def test_busy(self) -> None:
        root = Path(tempfile.mkdtemp())
        locks = ProjectLock(root)
        locks.acquire("Ab3K9", "t1")
        with self.assertRaises(ProjectLockBusy):
            locks.acquire("Ab3K9", "t2", timeout=0)
        locks.release("Ab3K9")
        locks.acquire("Ab3K9", "t2", timeout=0)
        locks.release("Ab3K9")

    def test_stale_lock_is_taken(self) -> None:
        root = Path(tempfile.mkdtemp())
        locks = ProjectLock(root)
        path = locks.acquire("Ab3K9", "old")
        os.utime(path, (0, 0))
        locks.acquire("Ab3K9", "new", timeout=0)
        locks.release("Ab3K9")
