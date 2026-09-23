"""Freeze wheels[] in build.lock.json from product_packages / agent_packages."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pypi_resolve import resolve_packages


def main() -> int:
    lock_path = ROOT / "build.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    product = resolve_packages(lock.get("product_packages") or [], "cp311")
    for item in product:
        item["role"] = "product"
    agent = resolve_packages(lock.get("agent_packages") or [], "cp314")
    for item in agent:
        item["role"] = "agent"
    lock["wheels"] = product + agent
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Pinned {len(product)} product wheels and {len(agent)} agent wheels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
