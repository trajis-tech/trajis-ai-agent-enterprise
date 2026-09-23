#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a read-only SQLite dependency knowledge DB from corpus.py (offline)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
import corpus  # noqa: E402

SCHEMA_SQL = (ROOT / "schema.sql").read_text(encoding="utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_lock() -> dict:
    path = REPO / "build.lock.json"
    return json.loads(path.read_text(encoding="utf-8"))


def extra_components_from_lock(lock: dict, existing: set[str]) -> list[dict]:
    extras = []
    for group, kind in (("product_packages", "library"), ("agent_packages", "library")):
        for item in lock.get(group) or []:
            name = item.get("name") or ""
            ident = name.replace("_", "-")
            if not ident or ident in existing:
                continue
            existing.add(ident)
            extras.append(
                {
                    "id": ident,
                    "name": name,
                    "version": item.get("version") or "unknown",
                    "version_status": "pinned" if item.get("version") else "unknown",
                    "kind": kind,
                    "platform": "python",
                    "upstream_url": "",
                    "license_spdx": "unknown",
                    "implementation_status": "official_implemented",
                }
            )
    return extras


def insert_component(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """INSERT INTO components(id,name,version,version_status,kind,platform,upstream_url,license_spdx,implementation_status)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            row["id"],
            row["name"],
            row["version"],
            row["version_status"],
            row["kind"],
            row["platform"],
            row["upstream_url"],
            row["license_spdx"],
            row["implementation_status"],
        ),
    )


def main() -> int:
    started = time.perf_counter()
    lock_path = REPO / "build.lock.json"
    lock = load_lock()
    lock_sha = sha256_file(lock_path)
    out_dir = ROOT
    db_path = out_dir / "dependencies.sqlite"
    if db_path.exists():
        db_path.unlink()
    for leftover in (out_dir / "dependencies.sqlite-wal", out_dir / "dependencies.sqlite-shm"):
        if leftover.exists():
            leftover.unlink()

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.executescript(SCHEMA_SQL)

    existing_ids = {c["id"] for c in corpus.COMPONENTS}
    components = list(corpus.COMPONENTS) + extra_components_from_lock(lock, existing_ids)
    for row in components:
        insert_component(conn, row)

    source_hashes = {}
    for src in corpus.SOURCES:
        payload = json.dumps(src, ensure_ascii=False, sort_keys=True)
        digest = sha256_text(payload)
        source_hashes[src["id"]] = digest
        conn.execute(
            """INSERT INTO sources(id,component_id,url,title,source_kind,doc_version,git_ref,retrieved_at,
                                   content_sha256,language,license_text,redistribution,verification_status)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                src["id"],
                src["component_id"],
                src["url"],
                src["title"],
                src["source_kind"],
                src["doc_version"],
                src["git_ref"],
                src["retrieved_at"],
                digest,
                src["language"],
                src["license_text"],
                src["redistribution"],
                src["verification_status"],
            ),
        )

    key_to_id: dict[str, int] = {}
    for chunk in corpus.CHUNKS:
        body = chunk["body"]
        summary = chunk["summary_zh_tw"]
        digest = sha256_text(chunk["stable_key"] + "\n" + body + "\n" + summary)
        cur = conn.execute(
            """INSERT INTO chunks(stable_key,source_id,section_anchor,heading,body,summary_zh_tw,keywords,
                                  applicability_json,implementation_status,confidence,content_sha256)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                chunk["stable_key"],
                chunk["source_id"],
                chunk["section_anchor"],
                chunk["heading"],
                body,
                summary,
                chunk["keywords"],
                chunk["applicability_json"],
                chunk["implementation_status"],
                chunk["confidence"],
                digest,
            ),
        )
        key_to_id[chunk["stable_key"]] = int(cur.lastrowid)

    for recipe in corpus.RECIPES:
        conn.execute(
            """INSERT INTO recipes(id,component_id,title,goal,prerequisites_json,steps_json,input_schema_json,
                                   output_schema_json,example_text,expected_result,side_effects_json,
                                   network_requirements_json,mode_requirements_json,validation_status,
                                   applicability_json,known_limits)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                recipe["id"],
                recipe["component_id"],
                recipe["title"],
                recipe["goal"],
                recipe["prerequisites_json"],
                recipe["steps_json"],
                recipe["input_schema_json"],
                recipe["output_schema_json"],
                recipe["example_text"],
                recipe["expected_result"],
                recipe["side_effects_json"],
                recipe["network_requirements_json"],
                recipe["mode_requirements_json"],
                recipe["validation_status"],
                recipe["applicability_json"],
                recipe["known_limits"],
            ),
        )
        for key in recipe["source_keys"]:
            chunk_id = key_to_id[key]
            conn.execute("INSERT INTO recipe_sources(recipe_id,chunk_id) VALUES(?,?)", (recipe["id"], chunk_id))

    for item in corpus.COMPATIBILITY:
        conn.execute(
            """INSERT INTO compatibility(id,component_a_id,component_b_id,relation,status,constraints_json,evidence_summary)
               VALUES(?,?,?,?,?,?,?)""",
            (
                item["id"],
                item["component_a_id"],
                item["component_b_id"],
                item["relation"],
                item["status"],
                item["constraints_json"],
                item["evidence_summary"],
            ),
        )
        for key in item["source_keys"]:
            conn.execute(
                "INSERT INTO compatibility_sources(compatibility_id,chunk_id) VALUES(?,?)",
                (item["id"], key_to_id[key]),
            )

    for alias, component_id, language in corpus.ALIASES:
        conn.execute(
            "INSERT OR IGNORE INTO aliases(alias,component_id,language) VALUES(?,?,?)",
            (alias, component_id, language),
        )

    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    conn.execute("INSERT INTO chunks_fts_trigram(chunks_fts_trigram) VALUES('rebuild')")

    inventory = {
        "lock_sha256": lock_sha,
        "product_python": lock.get("product_python"),
        "agent_python": lock.get("agent_python"),
        "node": lock.get("node"),
        "n8n_runtime": lock.get("n8n_runtime"),
        "components": components,
    }
    inventory_text = json.dumps(inventory, ensure_ascii=False, sort_keys=True, indent=2)
    inventory_sha = sha256_text(inventory_text)
    (out_dir / "inventory.json").write_text(inventory_text + "\n", encoding="utf-8")

    sqlite_ver = conn.execute("SELECT sqlite_version()").fetchone()[0]
    built_at = utc_now()
    meta = {
        "schema_version": "1",
        "corpus_version": corpus.CORPUS_VERSION,
        "built_at": built_at,
        "builder_version": corpus.BUILDER_VERSION,
        "input_lock_sha256": lock_sha,
        "sqlite_version": sqlite_ver,
        "inventory_sha256": inventory_sha,
        "tokenizer_strategy": "chunks_fts unicode61 (identifiers); chunks_fts_trigram trigram (substrings); short CJK via aliases+LIKE in reader",
    }
    for key, value in meta.items():
        conn.execute("INSERT INTO kb_meta(key,value) VALUES(?,?)", (key, value))

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    elapsed = time.perf_counter() - started
    sources_manifest = [
        {
            "id": src["id"],
            "url": src["url"],
            "retrieved_at": src["retrieved_at"],
            "verification_status": src["verification_status"],
            "content_sha256": source_hashes[src["id"]],
            "redistribution": src["redistribution"],
        }
        for src in corpus.SOURCES
    ]
    (out_dir / "sources.manifest.json").write_text(
        json.dumps(sources_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "gaps.md").write_text(corpus.GAPS, encoding="utf-8")

    detailed = {c["id"] for c in corpus.COMPONENTS}
    coverage_rows = []
    for row in components:
        coverage_rows.append(
            {
                "id": row["id"],
                "version": row["version"],
                "version_status": row["version_status"],
                "has_detailed_chunks": row["id"] in detailed,
                "implementation_status": row["implementation_status"],
            }
        )
    coverage = {
        "detailed_component_count": len(detailed),
        "inventory_component_count": len(components),
        "chunk_count": len(corpus.CHUNKS),
        "recipe_count": len(corpus.RECIPES),
        "components": coverage_rows,
    }
    (out_dir / "coverage.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    db_size = db_path.stat().st_size
    report = f"""# BUILD_REPORT

- built_at: {built_at}
- builder_version: {corpus.BUILDER_VERSION}
- corpus_version: {corpus.CORPUS_VERSION}
- input_lock_sha256: {lock_sha}
- sqlite_version (builder process): {sqlite_ver}
- chunks: {len(corpus.CHUNKS)}
- recipes: {len(corpus.RECIPES)}
- sources: {len(corpus.SOURCES)}
- db_bytes: {db_size}
- build_seconds: {elapsed:.3f}
- tokenizer: unicode61 + trigram external-content FTS (rowid = chunks.id)
- content_policy: official summaries + short quotes + URLs; no full-site mirror
- note: performance query percentiles are measured in validate_kb.py, not invented here
"""
    (out_dir / "BUILD_REPORT.md").write_text(report, encoding="utf-8")

    readme = """# 依賴知識庫建置目錄

本目錄獨立產出 `dependencies.sqlite`。通過 `validate_kb.py` 後再複製到 `filesystem/system/knowledge/dependencies.sqlite`。

## 可重現建置

在專案根目錄、使用產品 Python：

```
portable_python\\python.exe knowledge_build\\build_kb.py
portable_python\\python.exe knowledge_build\\validate_kb.py
```

建置為離線步驟：語料已寫入 `corpus.py`，內容來自建庫當日抓取的官方頁摘要，不是執行時上網。

## 離線查詢

```
portable_python\\python.exe knowledge_build\\query_kb.py search "OpenRPA 8771"
portable_python\\python.exe knowledge_build\\query_kb.py recipe r-openrpa-offline
```

## 版本更新

1. 依 `build.lock.json` 鎖定版本抓官方 tag 或官方文件。
2. 更新 `corpus.py`（禁止無來源補 API）。
3. 重建並跑 validate。
4. 以複製/版本檔切換產品 DB，不要覆寫正在開啟的檔案。

## 授權

DB 內為摘要與短引文。OpenRPA tag LICENSE 為 MPL-2.0；n8n@2.34.6 為 Sustainable Use License；CPython 為 PSF-2.0；SQLite 文件為公有領域。完整再散布請看各 `sources` 的 redistribution 欄。

## 匯入

產品 reader：`app/backend/knowledge.py`（`mode=ro`、`query_only`、allowlist 含 `kb_meta`）。
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")

    artifacts = [
        "dependencies.sqlite",
        "schema.sql",
        "build_kb.py",
        "query_kb.py",
        "validate_kb.py",
        "corpus.py",
        "sources.manifest.json",
        "inventory.json",
        "coverage.json",
        "gaps.md",
        "BUILD_REPORT.md",
        "README.md",
    ]
    lines = []
    for name in artifacts:
        path = out_dir / name
        if path.is_file():
            lines.append(f"{sha256_file(path)}  {name}")
    (out_dir / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("built", db_path, "bytes", db_size, "seconds", f"{elapsed:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
