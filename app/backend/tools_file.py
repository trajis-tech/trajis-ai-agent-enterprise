from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .audit import AuditLog
from .hashutil import sha256_file, sha256_text
from .jail import FilesystemJail, JailError
from .snapshot import SnapshotStore, controlled_delete, controlled_write


class ToolConflict(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "CONFLICT"


@dataclass
class FileContext:
    jail: FilesystemJail
    snapshots: SnapshotStore
    audit: AuditLog
    project_id: str
    turn_id: str
    project_root: Path
    cancel_event: Any = None


def ls(ctx: FileContext, path: str = ".") -> str:
    target = ctx.jail.resolve(path, "read")
    if not target.exists():
        raise FileNotFoundError(path)
    if target.is_file():
        return json.dumps({"path": path, "type": "file", "sha256": sha256_file(target)})
    items = []
    root = ctx.project_root.resolve()
    for child in sorted(target.iterdir()):
        try:
            rel = child.resolve().relative_to(root).as_posix()
            ctx.jail.resolve(rel, "read")
        except (JailError, ValueError):
            continue
        items.append({"name": child.name, "type": "dir" if child.is_dir() else "file"})
    return json.dumps(items, ensure_ascii=False)


def read_file(ctx: FileContext, path: str, max_chars: int = 80000) -> str:
    target = ctx.jail.resolve(path, "read")
    if not target.is_file():
        raise FileNotFoundError(path)
    data = target.read_text(encoding="utf-8", errors="replace")
    digest = sha256_file(target)
    if len(data) > max_chars:
        data = data[:max_chars] + "\n[truncated]"
    return json.dumps({"path": path, "sha256": digest, "content": data}, ensure_ascii=False)


def write_file(ctx: FileContext, path: str, content: str) -> str:
    data = content.encode("utf-8")
    dest = controlled_write(ctx.jail, path, data, ctx.snapshots, ctx.project_id, ctx.turn_id)
    ctx.audit.write(
        {
            "tool": "write_file",
            "project_id": ctx.project_id,
            "turn_id": ctx.turn_id,
            "target": path,
            "after_sha256": sha256_file(dest),
            "result": "ok",
        }
    )
    return json.dumps({"path": path, "sha256": sha256_file(dest)})


def edit_file(ctx: FileContext, path: str, old_text: str, new_text: str, expected_sha256: str) -> str:
    target = ctx.jail.resolve(path, "write")
    if not target.is_file():
        raise FileNotFoundError(path)
    current = sha256_file(target)
    if current.lower() != expected_sha256.lower():
        raise ToolConflict(f"expected_sha256 mismatch for {path}")
    text = target.read_text(encoding="utf-8")
    if old_text not in text:
        raise ToolConflict("old_text not found")
    updated = text.replace(old_text, new_text, 1)
    dest = controlled_write(ctx.jail, path, updated.encode("utf-8"), ctx.snapshots, ctx.project_id, ctx.turn_id)
    ctx.audit.write(
        {
            "tool": "edit_file",
            "project_id": ctx.project_id,
            "turn_id": ctx.turn_id,
            "target": path,
            "before_sha256": current,
            "after_sha256": sha256_file(dest),
            "result": "ok",
        }
    )
    return json.dumps({"path": path, "sha256": sha256_file(dest)})


def delete_file(ctx: FileContext, path: str) -> str:
    controlled_delete(ctx.jail, path, ctx.snapshots, ctx.project_id, ctx.turn_id)
    ctx.audit.write(
        {
            "tool": "delete_file",
            "project_id": ctx.project_id,
            "turn_id": ctx.turn_id,
            "target": path,
            "result": "deleted",
        }
    )
    return json.dumps({"path": path, "deleted": True})


def glob_files(ctx: FileContext, pattern: str) -> str:
    root = ctx.project_root.resolve()
    matches = []
    for path in root.glob(pattern):
        try:
            rel = path.resolve().relative_to(root).as_posix()
            ctx.jail.resolve(rel, "read")
        except (JailError, ValueError):
            continue
        matches.append(rel)
    return json.dumps(sorted(matches), ensure_ascii=False)


def grep_files(ctx: FileContext, query: str, pattern: str = "**/*") -> str:
    hits = []
    root = ctx.project_root.resolve()
    for path in root.glob(pattern):
        if not path.is_file():
            continue
        try:
            rel = path.resolve().relative_to(root).as_posix()
            ctx.jail.resolve(rel, "read")
        except (JailError, ValueError):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if query in line:
                hits.append({"path": rel, "line": i, "text": line[:400]})
                if len(hits) >= 200:
                    return json.dumps(hits, ensure_ascii=False)
    return json.dumps(hits, ensure_ascii=False)
