from __future__ import annotations

import json
import re
import secrets
import string
from pathlib import Path

from .atomic import atomic_write_text

CODE_ALPHABET = string.ascii_letters + string.digits
TITLE_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def random_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))


def sanitize_title(raw: str, max_len: int = 80) -> str:
    text = TITLE_BAD.sub("", (raw or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        raise ValueError("title is empty after sanitizing")
    return text[:max_len]


def parse_project_dir(name: str) -> tuple[str, str]:
    if "-" not in name:
        raise ValueError("illegal project folder name")
    code, title = name.split("-", 1)
    if len(code) != 5 or any(ch not in CODE_ALPHABET for ch in code):
        raise ValueError("illegal project code")
    if title in {".", ".."} or TITLE_BAD.search(title):
        raise ValueError("illegal project title")
    return code, title


def list_projects(projects_root: Path) -> list[dict[str, str]]:
    items = []
    if not projects_root.exists():
        return items
    for child in sorted(projects_root.iterdir()):
        if not child.is_dir() or child.is_symlink() or not child.resolve().is_relative_to(projects_root.resolve()):
            continue
        try:
            code, title = parse_project_dir(child.name)
        except ValueError:
            continue
        items.append({"id": code, "folder": child.name, "title": title, "path": str(child)})
    return items


def create_draft(projects_root: Path) -> dict[str, str]:
    projects_root.mkdir(parents=True, exist_ok=True)
    for _ in range(16):
        code = random_code()
        folder = projects_root / f"{code}-草稿"
        if folder.exists():
            continue
        folder.mkdir()
        (folder / "n8n" / "workflows").mkdir(parents=True)
        atomic_write_text(folder / "README.md", f"# {code}-草稿\n")
        atomic_write_text(
            folder / "n8n" / "deployment.json",
            json.dumps({"workflows": []}, ensure_ascii=False, indent=2),
        )
        return {"id": code, "folder": folder.name, "title": "草稿", "path": str(folder)}
    raise RuntimeError("could not allocate project code")


def rename_title(projects_root: Path, code: str, title: str) -> dict[str, str]:
    safe = sanitize_title(title)
    current = None
    for child in projects_root.iterdir():
        if child.is_dir() and child.name.startswith(f"{code}-"):
            current = child
            break
    if current is None:
        raise FileNotFoundError(code)
    dest = projects_root / f"{code}-{safe}"
    if dest.resolve() != current.resolve():
        if dest.exists():
            raise FileExistsError(str(dest))
        current.rename(dest)
    return {"id": code, "folder": dest.name, "title": safe, "path": str(dest)}
