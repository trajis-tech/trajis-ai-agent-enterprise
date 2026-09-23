from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .hashutil import sha256_file

Access = Literal["read", "write", "delete", "execute"]


class JailError(PermissionError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class JailPolicy:
    write_extensions: set[str] = field(default_factory=set)
    forbidden_names: set[str] = field(default_factory=lambda: {".env", "custom_api.json"})
    forbidden_suffixes: set[str] = field(default_factory=lambda: {".pem", ".key", ".p12", ".pfx"})


@dataclass
class FilesystemJail:
    fs_root: Path
    system_root: Path
    project_root: Path | None
    policy: JailPolicy = field(default_factory=JailPolicy)

    def __post_init__(self) -> None:
        self.fs_root = self.fs_root.resolve()
        self.system_root = self.system_root.resolve()
        if self.project_root is not None:
            self.project_root = self.project_root.resolve()

    def resolve(self, raw: str | Path, access: Access) -> Path:
        if raw is None or str(raw).strip() == "":
            raise JailError("EMPTY", "path is empty")
        text = str(raw).replace("/", "\\")
        if text.startswith("\\\\") or text.startswith("//") or text.startswith("\\\\?\\"):
            raise JailError("UNC", "UNC paths are denied")
        parts = text.split(chr(92))
        if ".." in parts:
            raise JailError("TRAVERSAL", "parent traversal is denied")
        if any(":" in part for part in parts[1:]) or (":" in parts[0] and not (len(parts[0]) == 2 and parts[0][1] == ":")):
            raise JailError("ADS", "alternate data streams are denied")
        path = Path(text)
        if path.is_absolute() or (len(text) >= 2 and text[1] == ":"):
            try:
                resolved_abs = Path(text).resolve(strict=False)
            except OSError as exc:
                raise JailError("RESOLVE", f"cannot resolve path: {exc}") from exc
            if not _is_relative_to(resolved_abs, self.fs_root):
                raise JailError("ABS", "absolute path outside filesystem/")
            path = resolved_abs
        elif not path.is_absolute():
            base = self.project_root if self.project_root is not None else self.fs_root
            path = base / path
        try:
            resolved = path.resolve(strict=False)
        except OSError as exc:
            raise JailError("RESOLVE", f"cannot resolve path: {exc}") from exc
        if not _is_relative_to(resolved, self.fs_root):
            raise JailError("OUTSIDE_FS", "path escapes filesystem/")
        runtime = self.fs_root / ".runtime"
        if _is_relative_to(resolved, runtime):
            raise JailError("RUNTIME", ".runtime is denied")
        projects = self.fs_root / "projects"
        if resolved == projects:
            raise JailError("PROJECTS_ROOT", "projects/ root is not a valid target")
        if _is_relative_to(resolved, self.system_root):
            if access in ("write", "delete"):
                raise JailError("SYSTEM_RO", "filesystem/system is read-only")
            if access == "execute":
                return self._check_forbidden(resolved)
            return self._check_forbidden(resolved)
        if self.project_root is None:
            raise JailError("NO_PROJECT", "no current project")
        if not _is_relative_to(resolved, self.project_root):
            if _is_relative_to(resolved, projects):
                raise JailError("SIBLING", "other projects are denied")
            raise JailError("OUTSIDE_PROJECT", "path is outside the current project")
        if access in ("write", "delete"):
            if resolved == self.project_root:
                raise JailError("PROJECT_ROOT", "cannot modify project root")
            self._check_write_name(resolved)
        return self._check_forbidden(resolved)

    def _check_forbidden(self, path: Path) -> Path:
        name = path.name.lower()
        if name in {n.lower() for n in self.policy.forbidden_names}:
            raise JailError("FORBIDDEN_NAME", f"forbidden file name: {path.name}")
        suffix = path.suffix.lower()
        if suffix in {s.lower() for s in self.policy.forbidden_suffixes}:
            raise JailError("FORBIDDEN_EXT", f"forbidden extension: {suffix}")
        if path.is_symlink():
            target = path.resolve(strict=False)
            if not _is_relative_to(target, self.fs_root):
                raise JailError("SYMLINK", "symlink escapes filesystem/")
            runtime = self.fs_root / ".runtime"
            if _is_relative_to(target, runtime):
                raise JailError("SYMLINK", "symlink into .runtime is denied")
            if self.project_root and not (
                _is_relative_to(target, self.project_root)
                or _is_relative_to(target, self.system_root)
            ):
                raise JailError("SYMLINK", "symlink target is not allowed")
        return path

    def _check_write_name(self, path: Path) -> None:
        if path.suffix and self.policy.write_extensions:
            if path.suffix.lower() not in {e.lower() for e in self.policy.write_extensions}:
                raise JailError("EXT", f"write extension not allowed: {path.suffix}")

    def expected_sha256(self, path: Path) -> str | None:
        if not path.exists() or not path.is_file():
            return None
        return sha256_file(path)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False
