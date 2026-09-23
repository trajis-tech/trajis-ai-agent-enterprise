"""GitHub Actions only: install the locked libraries the unit tests import.

Corporate computers must keep using build/install_runtime.bat. This script is not
that installer and is not invoked by 點此開始.bat.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WANTED = {"starlette", "httpx", "pyyaml", "pydantic-ai-slim"}


def specs() -> list[str]:
    lock = json.loads((ROOT / "build.lock.json").read_text(encoding="utf-8"))
    chosen: list[str] = []
    seen: set[str] = set()
    for item in lock["product_packages"]:
        name = item["name"]
        if name not in WANTED or name in seen:
            continue
        seen.add(name)
        extras = item.get("extras") or []
        package = name + (("[" + ",".join(extras) + "]") if extras else "")
        chosen.append(package + "==" + item["version"])
    missing = WANTED - seen
    if missing:
        raise SystemExit("build.lock.json is missing product packages: " + ", ".join(sorted(missing)))
    return chosen


def main() -> int:
    packages = specs()
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *packages])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
