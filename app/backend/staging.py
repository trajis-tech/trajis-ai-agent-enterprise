from __future__ import annotations

import filecmp
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .audit import AuditLog
from .hashutil import sha256_file
from .jail import FilesystemJail, JailError
from .job_object import JobLimits, JobObject
from .snapshot import SnapshotStore, controlled_delete, controlled_write


@dataclass
class StagingResult:
    exit_code: int
    stdout: str
    stderr: str
    committed: list[str]
    truncated: bool
    violation: str | None = None


def _skip_rel(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    return ".tmp" in parts or "__pycache__" in parts or parts[-1].endswith(".pyc")


def tree_hashes(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for path in root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            if _skip_rel(rel):
                continue
            out[rel] = sha256_file(path)
    return out


def copy_project(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def restore_project(mirror: Path, project_root: Path) -> None:
    for child in list(project_root.iterdir()):
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in mirror.iterdir():
        dest = project_root / child.name
        if child.is_dir():
            shutil.copytree(child, dest)
        else:
            shutil.copy2(child, dest)


def _files(root: Path) -> set[str]:
    if not root.exists():
        return set()
    out = set()
    for path in root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            if not _skip_rel(rel):
                out.add(rel)
    return out


def diff_trees(original: Path, staging: Path) -> list[tuple[str, str]]:
    changes: list[tuple[str, str]] = []
    orig_files = _files(original)
    stag_files = _files(staging)
    for rel in sorted(stag_files - orig_files):
        changes.append((rel, "add"))
    for rel in sorted(orig_files - stag_files):
        changes.append((rel, "delete"))
    for rel in sorted(orig_files & stag_files):
        left = original / rel
        right = staging / rel
        if not filecmp.cmp(left, right, shallow=False):
            changes.append((rel, "modify"))
    return changes


def run_in_staging(
    *,
    interpreter: Path,
    script_rel: str,
    args: list[str],
    project_root: Path,
    staging_root: Path,
    jail: FilesystemJail,
    snapshots: SnapshotStore,
    project_id: str,
    turn_id: str,
    audit: AuditLog,
    timeout: int,
    limits: JobLimits,
    stdout_limit: int,
    pythonhome: Path,
    cancel_event=None,
) -> StagingResult:
    before = tree_hashes(project_root)
    before_root = staging_root / f"{turn_id}.before"
    staging = staging_root / turn_id
    copy_project(project_root, before_root)
    copy_project(before_root, staging)
    script_in_staging = staging / script_rel
    if not script_in_staging.is_file():
        raise FileNotFoundError(script_rel)

    env = {
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
        "WINDIR": os.environ.get("WINDIR", r"C:\Windows"),
        "TEMP": str(staging / ".tmp"),
        "TMP": str(staging / ".tmp"),
        "PYTHONHOME": str(pythonhome),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "MPLBACKEND": "Agg",
    }
    (staging / ".tmp").mkdir(exist_ok=True)
    cmd = [str(interpreter), str(script_in_staging), *args]
    proc = subprocess.Popen(
        cmd,
        cwd=str(staging),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    job = JobObject(limits)
    try:
        if proc.pid:
            try:
                job.assign(proc.pid)
            except OSError:
                pass
        deadline = time.monotonic() + timeout
        while True:
            if (cancel_event is not None and cancel_event.is_set()) or time.monotonic() >= deadline:
                job.close()
                if proc.poll() is None:
                    proc.kill()
                stdout, stderr = proc.communicate()
                stderr = (stderr or "") + "\n[cancelled or timeout: staging changes discarded]"
                break
            try:
                stdout, stderr = proc.communicate(timeout=min(0.25, max(0.01, deadline - time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        job.close()

    truncated = False
    if stdout and len(stdout.encode("utf-8")) > stdout_limit:
        stdout = stdout.encode("utf-8")[:stdout_limit].decode("utf-8", errors="replace") + "\n[truncated]"
        truncated = True
    if stderr and len(stderr.encode("utf-8")) > stdout_limit:
        stderr = stderr.encode("utf-8")[:stdout_limit].decode("utf-8", errors="replace") + "\n[truncated]"
        truncated = True

    after_real = tree_hashes(project_root)
    if after_real != before:
        restore_project(before_root, project_root)
        audit.write(
            {
                "tool": "run_python",
                "result": "VIOLATION",
                "project_id": project_id,
                "turn_id": turn_id,
                "target": "project_direct_write",
            }
        )
        shutil.rmtree(before_root, ignore_errors=True)
        return StagingResult(
            exit_code=proc.returncode if proc.returncode is not None else 1,
            stdout=stdout or "",
            stderr=(stderr or "") + "\n[violation] script modified the real project; restored and commit aborted",
            committed=[],
            truncated=truncated,
            violation="REAL_PROJECT_MUTATED",
        )
    shutil.rmtree(before_root, ignore_errors=True)

    if proc.returncode != 0 or (cancel_event is not None and cancel_event.is_set()):
        return StagingResult(exit_code=proc.returncode or 1, stdout=stdout or "", stderr=stderr or "",
                             committed=[], truncated=truncated)

    committed: list[str] = []
    for rel, kind in diff_trees(project_root, staging):
        try:
            if kind == "delete":
                controlled_delete(jail, rel, snapshots, project_id, turn_id)
            else:
                data = (staging / rel).read_bytes()
                controlled_write(jail, rel, data, snapshots, project_id, turn_id)
            committed.append(f"{kind}:{rel}")
            audit.write(
                {
                    "tool": "run_python_commit",
                    "project_id": project_id,
                    "turn_id": turn_id,
                    "target": rel,
                    "result": kind,
                }
            )
        except JailError as exc:
            audit.write(
                {
                    "tool": "run_python_commit",
                    "project_id": project_id,
                    "turn_id": turn_id,
                    "target": rel,
                    "result": "DENIED",
                    "code": exc.code,
                }
            )
            stderr = (stderr or "") + f"\n[commit denied] {rel}: {exc.message}"
    return StagingResult(
        exit_code=proc.returncode if proc.returncode is not None else 1,
        stdout=stdout or "",
        stderr=stderr or "",
        committed=committed,
        truncated=truncated,
    )
