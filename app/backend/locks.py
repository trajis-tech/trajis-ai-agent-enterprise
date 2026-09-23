from __future__ import annotations

import time
from pathlib import Path

STALE_SECONDS = 15 * 60


class ProjectLockBusy(RuntimeError):
    pass


class ProjectLock:
    def __init__(self, runtime_root: Path) -> None:
        self.root = runtime_root / "locks"
        self.root.mkdir(parents=True, exist_ok=True)

    def acquire(self, project_id: str, holder: str, timeout: float = 0.0) -> Path:
        lock_path = self.root / f"{project_id}.lock"
        deadline = time.time() + timeout
        while True:
            try:
                fd = open(lock_path, "x", encoding="utf-8")
                fd.write(holder)
                fd.close()
                return lock_path
            except FileExistsError:
                if _stale(lock_path):
                    try:
                        lock_path.unlink()
                        continue
                    except OSError:
                        pass
                if time.time() >= deadline:
                    raise ProjectLockBusy(f"project {project_id} is busy")
                time.sleep(0.05)

    def release(self, project_id: str) -> None:
        lock_path = self.root / f"{project_id}.lock"
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _stale(lock_path: Path) -> bool:
    try:
        return (time.time() - lock_path.stat().st_mtime) > STALE_SECONDS
    except OSError:
        return False
