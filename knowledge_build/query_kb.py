#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline CLI over the product read-only knowledge reader."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "app"))
from backend.knowledge import get_dependency_doc, get_recipe, search_dependency_docs  # noqa: E402


def db_path() -> Path:
    arg = next((item for item in sys.argv[1:] if item.endswith(".sqlite")), None)
    if arg:
        return Path(arg)
    candidate = Path(__file__).resolve().parent / "dependencies.sqlite"
    if candidate.is_file():
        return candidate
    return REPO / "filesystem" / "system" / "knowledge" / "dependencies.sqlite"


def main() -> int:
    args = [item for item in sys.argv[1:] if not item.endswith(".sqlite")]
    path = db_path()
    if not args:
        print("usage: query_kb.py [db] search <query> | doc <id> | recipe <id>", file=sys.stderr)
        return 2
    cmd = args[0]
    if cmd == "search":
        query = " ".join(args[1:]) or ""
        payload = search_dependency_docs(path, query)
    elif cmd == "doc":
        payload = get_dependency_doc(path, int(args[1]))
    elif cmd == "recipe":
        payload = get_recipe(path, args[1])
    else:
        print("unknown command", cmd, file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
