#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate the built knowledge DB: integrity, FTS, readonly, eval cases."""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO / "app"))
from backend.knowledge import (  # noqa: E402
    _assert_schema,
    _open,
    get_recipe,
    knowledge_status,
    search_dependency_docs,
)

EVAL_CASES = [
    {
        "id": "e01",
        "query": "OpenRPA 內建 8771 API 嗎",
        "expect_any": ["不是官方", "不是", "自製", "沒有"],
        "forbid_any": ["OpenRPA 官方 REST 位於 8771", "OpenRPA built-in REST on 8771"],
        "notes": "must not claim OpenRPA ships 8771",
    },
    {
        "id": "e02",
        "query": "Python staging 是否 OS 沙箱",
        "expect_any": ["不是 OS 沙箱", "不是 Windows OS 沙箱", "不是"],
        "forbid_any": [],
    },
    {
        "id": "e03",
        "query": "Plan 能 publish 嗎",
        "expect_any": ["不能", "不可", "plan"],
        "forbid_any": [],
    },
    {"id": "e04", "query": "wsurl offline settings.json", "expect_any": ["wsurl", "Documents"], "forbid_any": []},
    {"id": "e05", "query": "OpenRPA.exe /WorkflowID", "expect_any": ["WorkflowID", "workflowid"], "forbid_any": []},
    {"id": "e06", "query": "Invoke-OpenRPA wait complete", "expect_any": ["Invoke-OpenRPA", "out"], "forbid_any": []},
    {"id": "e07", "query": "N8N_CUSTOM_EXTENSIONS", "expect_any": ["N8N_CUSTOM_EXTENSIONS"], "forbid_any": []},
    {"id": "e08", "query": "format json 403 settings.yml", "expect_any": ["403"], "forbid_any": []},
    {"id": "e09", "query": "tools/list tools/call isError", "expect_any": ["tools/list", "tools/call"], "forbid_any": []},
    {"id": "e10", "query": "DeferredToolRequests", "expect_any": ["DeferredToolRequests"], "forbid_any": []},
    {"id": "e11", "query": "unicode61 中文斷詞", "expect_any": ["不做", "不是", "斷詞"], "forbid_any": []},
    {"id": "e12", "query": "PRAGMA query_only SQLITE_READONLY", "expect_any": ["query_only"], "forbid_any": []},
    {"id": "e13", "query": "Origin header DNS rebinding", "expect_any": ["Origin"], "forbid_any": []},
    {"id": "e14", "query": "MCP stderr stdio", "expect_any": ["stderr"], "forbid_any": []},
    {"id": "e15", "query": "SIGTERM SIGKILL initialize", "expect_any": ["SIGTERM", "initialize"], "forbid_any": []},
    {"id": "e16", "query": "workflowCreate name nodes connections settings", "expect_any": ["name", "settings"], "forbid_any": []},
    {"id": "e17", "query": "active readOnly workflowCreate", "expect_any": ["readOnly", "active"], "forbid_any": []},
    {"id": "e18", "query": "X-N8N-API-KEY", "expect_any": ["X-N8N-API-KEY"], "forbid_any": []},
    {"id": "e19", "query": "embeddable pip vendoring", "expect_any": ["pip"], "forbid_any": []},
    {"id": "e20", "query": "Python 3.11.9", "expect_any": ["3.11.9"], "forbid_any": []},
    {"id": "e21", "query": "time_range day month year", "expect_any": ["time_range"], "forbid_any": []},
    {"id": "e22", "query": "High Density OpenCore", "expect_any": ["OpenCore", "High Density"], "forbid_any": []},
    {"id": "e23", "query": "CUSTOM.localOpenRpa community", "expect_any": ["私有", "不是官方"], "forbid_any": []},
    {"id": "e24", "query": "MPL-2.0 OpenRPA LICENSE", "expect_any": ["MPL-2.0"], "forbid_any": []},
    {"id": "e25", "query": "Sustainable Use License n8n", "expect_any": ["Sustainable Use"], "forbid_any": []},
    {"id": "e26", "query": "trigram substring", "expect_any": ["trigram"], "forbid_any": []},
    {"id": "e27", "query": "pydantic-ai-slim 2.31.0 deferred_tool_results", "expect_any": ["2.31.0"], "forbid_any": []},
    {"id": "e28", "query": "SQLite 3.45.1 FTS5", "expect_any": ["3.45.1"], "forbid_any": []},
    {"id": "e29", "query": "沙箱", "expect_any": ["沙箱"], "forbid_any": []},
    {"id": "e30", "query": "n8n-nodes", "expect_any": [], "empty_ok": True, "forbid_any": []},
    {"id": "e31", "query": "publish_automation_bundle plan", "expect_any": ["plan", "publish"], "forbid_any": []},
    {"id": "e32", "query": "localhost 不是 OS 沙箱", "expect_any": ["沙箱", "localhost"], "forbid_any": []},
    {"id": "e33", "query": "SearXNG /search JSON", "expect_any": ["/search"], "forbid_any": []},
    {"id": "e34", "query": "8772 MCP HTTP proposed", "expect_any": ["8772", "proposed", "選配"], "forbid_any": []},
    {"id": "e35", "query": "批准部署 啟用 n8n", "expect_any": ["批准部署", "啟用"], "forbid_any": []},
    {"id": "e36", "query": "n8n 2.34.6 POST publish", "expect_any": ["publish", "2.34.6"], "forbid_any": []},
    {"id": "e37", "query": "engines >=22.22 22.23.2", "expect_any": [">=22.22", "22.23.2"], "forbid_any": []},
    {"id": "e38", "query": "N8N_CUSTOM_EXTENSIONS 2.34.6 semicolon", "expect_any": ["N8N_CUSTOM_EXTENSIONS"], "forbid_any": []},
    {"id": "e39", "query": "OpenRPA.exe.config 4.6.2", "expect_any": ["4.6.2"], "forbid_any": []},
    {"id": "e40", "query": "uvicorn run 127.0.0.1 8000", "expect_any": ["127.0.0.1", "8000"], "forbid_any": []},
    {"id": "e41", "query": "httpx Timeout 5.0", "expect_any": ["5.0", "Timeout"], "forbid_any": []},
    {"id": "e42", "query": "Broker Origin 403", "expect_any": ["403"], "forbid_any": []},
    {"id": "e43", "query": "WorkingDir workingdir", "expect_any": ["WorkingDir"], "forbid_any": []},
]


def _blob(hit: dict) -> str:
    return " ".join(
        str(hit.get(key) or "")
        for key in ("title", "snippet", "source_url", "section_anchor", "implementation_status")
    )


def eval_case(path: Path, case: dict) -> dict:
    started = time.perf_counter()
    try:
        result = search_dependency_docs(path, case["query"])
        err = ""
    except Exception as exc:
        result = {"results": [], "error": str(exc)}
        err = str(exc)
    elapsed_ms = (time.perf_counter() - started) * 1000
    text = " ".join(_blob(hit) for hit in result.get("results") or [])
    ok = True
    reasons = []
    if err and not case.get("allow_error"):
        ok = False
        reasons.append("error:" + err)
    if case.get("empty_ok") and not case.get("expect_any"):
        pass
    else:
        if not (result.get("results") or []) and not case.get("empty_ok"):
            ok = False
            reasons.append("no_hits")
        for needle in case.get("expect_any") or []:
            if needle.lower() not in text.lower():
                # one-of group: record miss then require any later
                pass
        if case.get("expect_any"):
            if not any(needle.lower() in text.lower() for needle in case["expect_any"]):
                ok = False
                reasons.append("missing_expect_any")
    for needle in case.get("forbid_any") or []:
        if needle and needle.lower() in text.lower():
            ok = False
            reasons.append("forbid:" + needle)
    return {
        "id": case["id"],
        "query": case["query"],
        "ok": ok,
        "reasons": reasons,
        "hits": len(result.get("results") or []),
        "elapsed_ms": round(elapsed_ms, 3),
        "first_snippet": ((result.get("results") or [{}])[0].get("snippet") or "")[:240],
    }


def main() -> int:
    db = ROOT / "dependencies.sqlite"
    if not db.is_file():
        print("missing", db, file=sys.stderr)
        return 2
    status = knowledge_status(db)
    if not status.get("available"):
        print("reader rejected db:", status, file=sys.stderr)
        return 1

    conn = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()
    if integrity != "ok":
        print("integrity_check", integrity, file=sys.stderr)
        return 1
    if fk:
        print("foreign_key_check", fk, file=sys.stderr)
        return 1

    with _open(db) as ro:
        _assert_schema(ro)
        try:
            ro.execute("INSERT INTO aliases VALUES ('x','openrpa','zz')")
            print("readonly insert unexpectedly succeeded", file=sys.stderr)
            return 1
        except sqlite3.OperationalError:
            pass
        fts_count = ro.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        chunk_count = ro.execute("SELECT count(*) FROM chunks").fetchone()[0]
        if fts_count != chunk_count:
            print("fts mismatch", fts_count, chunk_count, file=sys.stderr)
            return 1

    for recipe_id in (
        "r-openrpa-offline",
        "r-openrpa-cli",
        "r-n8n-custom-nodes",
        "r-n8n-workflow-api",
        "r-searxng-search-json",
        "r-mcp-stdio",
        "r-pydantic-deferred",
        "r-sqlite-fts",
        "r-product-modes",
        "r-offline-packaging",
    ):
        rec = get_recipe(db, recipe_id)
        if not rec.get("found") or not rec["recipe"].get("sources"):
            print("recipe missing sources", recipe_id, rec, file=sys.stderr)
            return 1

    version_hits = search_dependency_docs(db, "offline", version="9.9.9")
    if version_hits.get("results") and version_hits["results"][0]["match_kind"] != "reference_only":
        print("version mismatch should be reference_only", file=sys.stderr)
        return 1

    alias_hits = search_dependency_docs(db, "offline", component="OpenRPA")
    if not alias_hits.get("results") or any(item.get("component") != "OpenRPA" for item in alias_hits["results"]):
        print("component alias OpenRPA should resolve to OpenRPA chunks", alias_hits, file=sys.stderr)
        return 1
    n8n_offline = search_dependency_docs(db, "offline", component="n8n")
    if n8n_offline.get("results") and any(item.get("component") == "OpenRPA" for item in n8n_offline["results"]):
        print("n8n component filter leaked OpenRPA rows", n8n_offline, file=sys.stderr)
        return 1

    empty_ok = False
    try:
        search_dependency_docs(db, "   ")
    except ValueError:
        empty_ok = True
    if not empty_ok:
        print("empty query should raise", file=sys.stderr)
        return 1

    for query in ('" OR 1=1', "()", "*", "n8n-nodes", "依賴", "emoji😀"):
        search_dependency_docs(db, query)

    wal = Path(str(db) + "-wal")
    shm = Path(str(db) + "-shm")
    if wal.exists() or shm.exists():
        print("unexpected wal/shm", file=sys.stderr)
        return 1

    results = [eval_case(db, case) for case in EVAL_CASES]
    times = [row["elapsed_ms"] for row in results]
    times_sorted = sorted(times)
    p50 = statistics.median(times_sorted)
    p95 = times_sorted[max(0, int(round(0.95 * (len(times_sorted) - 1))))]
    failed = [row for row in results if not row["ok"]]
    payload = {
        "db": str(db),
        "chunks": status.get("chunks"),
        "eval_count": len(results),
        "eval_failed": len(failed),
        "p50_ms": round(p50, 3),
        "p95_ms": round(p95, 3),
        "samples_ms": times,
        "machine_note": "measured on builder host during validate_kb.py; not a published SLA",
        "cases": results,
    }
    (ROOT / "eval_cases.json").write_text(json.dumps(EVAL_CASES, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "eval_results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    import hashlib
    checksum_names = [
        "dependencies.sqlite", "schema.sql", "build_kb.py", "query_kb.py", "validate_kb.py",
        "corpus.py", "sources.manifest.json", "inventory.json", "coverage.json", "gaps.md",
        "eval_cases.json", "eval_results.json", "BUILD_REPORT.md", "README.md",
    ]
    lines = []
    for name in checksum_names:
        path = ROOT / name
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {name}")
    (ROOT / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"ok": not failed, "failed": [row["id"] for row in failed], "p50_ms": payload["p50_ms"], "p95_ms": payload["p95_ms"]}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
