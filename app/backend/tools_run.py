from __future__ import annotations

import json
from pathlib import Path

from .audit import AuditLog
from .hashutil import sha256_file
from .job_object import JobLimits
from .policy import Policy
from .staging import StagingResult, run_in_staging
from .tools_file import FileContext


def _interpreter_allowed(interpreter: Path, pythonhome: Path) -> bool:
    try:
        resolved = interpreter.resolve()
        home = pythonhome.resolve()
    except OSError:
        return False
    if not resolved.name.lower().startswith("python"):
        return False
    try:
        resolved.relative_to(home)
    except ValueError:
        return False
    return True


def run_python(ctx: FileContext, script_path: str, args: list[str] | None, policy: Policy, interpreter: Path, staging_root: Path, pythonhome: Path) -> str:
    target = ctx.jail.resolve(script_path, "read")
    if not target.is_file() or target.suffix.lower() != ".py":
        raise FileNotFoundError(script_path)
    if not _interpreter_allowed(interpreter, pythonhome):
        raise PermissionError("interpreter not allowed")
    rel = target.relative_to(ctx.project_root).as_posix()
    limits = JobLimits(
        memory_bytes=policy.run_memory,
        cpu_100ns=policy.run_cpu_seconds * 10_000_000,
        active_process_limit=policy.run_process_limit,
    )
    result: StagingResult = run_in_staging(
        interpreter=interpreter,
        script_rel=rel,
        args=list(args or []),
        project_root=ctx.project_root,
        staging_root=staging_root,
        jail=ctx.jail,
        snapshots=ctx.snapshots,
        project_id=ctx.project_id,
        turn_id=ctx.turn_id,
        audit=ctx.audit,
        timeout=policy.run_timeout,
        limits=limits,
        stdout_limit=policy.stdout_limit,
        pythonhome=pythonhome,
        cancel_event=ctx.cancel_event,
    )
    ctx.audit.write(
        {
            "tool": "run_python",
            "project_id": ctx.project_id,
            "turn_id": ctx.turn_id,
            "target": rel,
            "arguments_hash": sha256_file(target) if target.exists() else "",
            "result": "ok" if result.violation is None else result.violation,
            "exit_code": result.exit_code,
            "stdout_truncated": result.truncated,
        }
    )
    return json.dumps(
        {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "committed": result.committed,
            "violation": result.violation,
        },
        ensure_ascii=False,
    )
