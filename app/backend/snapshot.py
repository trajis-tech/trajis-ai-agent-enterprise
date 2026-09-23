from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .atomic import atomic_copy, atomic_write_bytes, atomic_write_text
from .hashutil import sha256_file
from .jail import FilesystemJail, JailError


class SnapshotStore:
    def __init__(self, snapshots_root: Path) -> None:
        self.root = snapshots_root
        self.root.mkdir(parents=True, exist_ok=True)

    def turn_dir(self, project_id: str, turn_id: str) -> Path:
        self._validate_ids(project_id, turn_id)
        path = self.root / project_id / f"turn_{turn_id}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _validate_ids(project_id: str, turn_id: str) -> None:
        if not all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value)
                   for value in (project_id, turn_id)):
            raise ValueError("無效的專案或回合識別碼")

    def ensure_before(self, project_id: str, turn_id: str, rel: str, src: Path) -> None:
        rel_path = Path(rel.replace(chr(92), "/"))
        if rel_path.is_absolute() or ".." in rel_path.parts or ":" in rel:
            raise ValueError("snapshot path must be project-relative")
        turn = self.turn_dir(project_id, turn_id)
        manifest_path = turn / "manifest.json"
        manifest = _load_manifest(manifest_path)
        if rel in manifest.get("files", {}):
            return
        dest = turn / "before" / rel.replace("\\", "/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        record = {"path": rel, "existed": src.exists()}
        if src.exists() and src.is_file():
            atomic_copy(src, dest)
            record["before_sha256"] = sha256_file(src)
        elif src.exists() and src.is_dir():
            shutil.copytree(src, dest, dirs_exist_ok=True)
            record["kind"] = "dir"
        manifest.setdefault("files", {})[rel] = record
        atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))

    def record_after(self, project_id: str, turn_id: str, rel: str, dest: Path) -> None:
        rel_path = Path(rel.replace(chr(92), "/"))
        if rel_path.is_absolute() or ".." in rel_path.parts or ":" in rel:
            raise ValueError("snapshot path must be project-relative")
        turn = self.turn_dir(project_id, turn_id)
        manifest_path = turn / "manifest.json"
        manifest = _load_manifest(manifest_path)
        entry = manifest.setdefault("files", {}).setdefault(rel, {"path": rel})
        if dest.exists() and dest.is_file():
            entry["after_sha256"] = sha256_file(dest)
            entry["operation"] = "write"
        else:
            entry["operation"] = "delete"
        atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))

    def restore_turn(self, project_id: str, turn_id: str, jail: FilesystemJail) -> list[str]:
        self._validate_ids(project_id, turn_id)
        turn = self.root / project_id / f"turn_{turn_id}"
        manifest = _load_manifest(turn / "manifest.json")
        if manifest.get("restored"):
            raise SnapshotConflict("此回合已復原，不能重複復原")
        # Preflight every target before restoring any file.
        for rel, info in manifest.get("files", {}).items():
            target = jail.resolve(rel, "write")
            before = turn / "before" / rel.replace(chr(92), "/")
            if not before.resolve().is_relative_to((turn / "before").resolve()):
                raise SnapshotConflict("快照路徑無效")
            expected = info.get("after_sha256") if info.get("operation") == "write" else None
            actual = sha256_file(target) if target.is_file() else None
            if actual != expected or (expected is None and target.exists()):
                raise SnapshotConflict(f"{rel} 在此回合後已變更，未復原任何檔案")
            if info.get("existed"):
                if not before.exists():
                    raise SnapshotConflict(f"{rel} 的原始快照遺失")
                if before.is_file() and sha256_file(before) != info.get("before_sha256"):
                    raise SnapshotConflict(f"{rel} 的原始快照損壞")
        restored: list[str] = []
        for rel, info in manifest.get("files", {}).items():
            target = jail.resolve(rel, "write")
            before = turn / "before" / rel.replace("\\", "/")
            if info.get("existed") and before.exists():
                if before.is_file():
                    atomic_copy(before, target)
                else:
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.copytree(before, target)
            else:
                if target.exists() and target.is_file():
                    target.unlink()
                elif target.exists() and target.is_dir():
                    shutil.rmtree(target)
            restored.append(rel)
        if restored:
            manifest["restored"] = True
            atomic_write_text(turn / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return restored


class SnapshotConflict(RuntimeError):
    pass


def controlled_write(jail: FilesystemJail, rel: str, data: bytes, snapshots: SnapshotStore, project_id: str, turn_id: str) -> Path:
    path = jail.resolve(rel, "write")
    rel = path.relative_to(jail.project_root).as_posix()
    snapshots.ensure_before(project_id, turn_id, rel, path)
    atomic_write_bytes(path, data)
    snapshots.record_after(project_id, turn_id, rel, path)
    return path


def controlled_delete(jail: FilesystemJail, rel: str, snapshots: SnapshotStore, project_id: str, turn_id: str) -> Path:
    path = jail.resolve(rel, "delete")
    if path.is_dir():
        raise JailError("DIRECTORY_DELETE", "delete_file only accepts individual files")
    rel = path.relative_to(jail.project_root).as_posix()
    snapshots.ensure_before(project_id, turn_id, rel, path)
    if path.exists() and path.is_file():
        path.unlink()
    snapshots.record_after(project_id, turn_id, rel, path)
    return path


def _load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"files": {}}
    return json.loads(path.read_text(encoding="utf-8"))
