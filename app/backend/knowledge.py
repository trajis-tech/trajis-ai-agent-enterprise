"""Read-only dependency knowledge retrieval. Does not create or populate the DB."""
from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

CORE_TABLES = {
    "kb_meta",
    "components",
    "sources",
    "chunks",
    "recipes",
    "recipe_sources",
    "compatibility",
    "compatibility_sources",
    "aliases",
}
FTS_TABLES = {"chunks_fts", "chunks_fts_trigram"}
TOKEN = re.compile(r"[A-Za-z0-9_.-]{2,40}|[\u4e00-\u9fff]{1,8}")
LIKE_ESCAPE = "\\"


def knowledge_path(system_root: Path) -> Path:
    return system_root / "knowledge" / "dependencies.sqlite"


def knowledge_status(path: Path) -> dict:
    if not path.is_file():
        return {
            "available": False,
            "path": str(path),
            "reason": "尚未匯入依賴知識庫。請將 knowledge_build 產出並通過驗證的 dependencies.sqlite 放到 filesystem/system/knowledge/。",
        }
    try:
        with _open(path) as conn:
            _assert_schema(conn)
            chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {"available": True, "path": str(path), "chunks": chunks, "reason": ""}
    except Exception as exc:
        return {"available": False, "path": str(path), "reason": "知識庫無法唯讀開啟：" + str(exc)}


def search_dependency_docs(path: Path, query: str, component: str | None = None, version: str | None = None, limit: int = 8) -> dict:
    status = knowledge_status(path)
    if not status["available"]:
        return {**status, "results": []}
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError("檢索字串需為 1–2000 字元")
    if not 1 <= int(limit) <= 20:
        raise ValueError("limit 需為 1–20")
    component = _optional_ident(component)
    version = _optional_version(version)
    if component is not None and not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", component):
        raise ValueError("component 識別碼格式無效")
    if version is not None and not re.fullmatch(r"[A-Za-z0-9._+-]{1,40}", version):
        raise ValueError("version 格式無效")
    tokens = TOKEN.findall(query)[:12]
    if not tokens:
        return {"available": True, "query": query.strip()[:200], "results": [], "warnings": ["沒有可索引的檢索詞"]}
    with _open(path) as conn:
        _assert_schema(conn)
        resolved = _resolve_component(conn, component)
        rows = _search_rows(conn, tokens, resolved, version, int(limit))
    results = [_row_result(row, version) for row in rows]
    payload = {"available": True, "query": query.strip()[:200], "results": results, "warnings": []}
    if version and results and all(item["match_kind"] == "reference_only" for item in results):
        payload["warnings"].append("指定版本沒有直接證據；下列僅供對照，不可當成該版本已驗證。")
    return _bounded(payload)


def get_dependency_doc(path: Path, chunk_id: int) -> dict:
    status = knowledge_status(path)
    if not status["available"]:
        return status
    if type(chunk_id) is not int or chunk_id < 1:
        raise ValueError("chunk_id 無效")
    with _open(path) as conn:
        _assert_schema(conn)
        row = conn.execute(_DOC_SQL + " WHERE c.id=?", (chunk_id,)).fetchone()
    if row is None:
        return {"available": True, "found": False, "reason": "找不到該文件片段"}
    document = _row_result(row, None)
    document["body"] = row["body"]
    document["summary_zh_tw"] = row["summary_zh_tw"]
    return _bounded({"available": True, "found": True, "document": document})


def get_recipe(path: Path, recipe_id: str) -> dict:
    status = knowledge_status(path)
    if not status["available"]:
        return status
    if not isinstance(recipe_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", recipe_id):
        raise ValueError("recipe_id 格式無效")
    with _open(path) as conn:
        _assert_schema(conn)
        row = conn.execute(
            """SELECT r.id, r.title, r.goal, r.prerequisites_json, r.steps_json, r.expected_result,
                      r.side_effects_json, r.network_requirements_json, r.mode_requirements_json,
                      r.validation_status, r.known_limits, r.example_text, p.name AS component, p.version
               FROM recipes r JOIN components p ON p.id=r.component_id WHERE r.id=?""",
            (recipe_id,),
        ).fetchone()
        sources = []
        if row is not None:
            sources = [dict(item) for item in conn.execute(
                """SELECT c.id AS chunk_id, c.heading, s.url, s.verification_status
                   FROM recipe_sources rs JOIN chunks c ON c.id=rs.chunk_id
                   JOIN sources s ON s.id=c.source_id WHERE rs.recipe_id=?""",
                (recipe_id,),
            ).fetchall()]
    if row is None:
        return {"available": True, "found": False, "reason": "找不到該 recipe"}
    data = dict(row)
    data["sources"] = sources
    return _bounded({"available": True, "found": True, "recipe": data})


@contextmanager
def _open(path: Path):
    conn = _connect(path)
    try:
        yield conn
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()


def _connect(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    try:
        conn.enable_load_extension(False)
    except Exception:
        pass
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA trusted_schema=OFF")
    deadline = time.monotonic() + 2

    def progress() -> int:
        return 1 if time.monotonic() > deadline else 0

    conn.set_progress_handler(progress, 8000)
    return conn


def _assert_schema(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT name, type, tbl_name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
    for name, typ, tbl in rows:
        if typ == "table" and name not in CORE_TABLES and not _fts_or_shadow(name):
            raise ValueError("知識庫含有未允許的資料表：" + name)
        if typ == "trigger" and not (_fts_or_shadow(name) or _fts_or_shadow(tbl)):
            raise ValueError("知識庫含有未允許的 trigger：" + name)
        if typ == "view":
            raise ValueError("知識庫不允許自訂 view：" + name)
    missing = CORE_TABLES - {row[0] for row in rows if row[1] == "table"}
    if missing:
        raise ValueError("知識庫缺少必要資料表：" + ",".join(sorted(missing)))


def _fts_or_shadow(name: str) -> bool:
    return any(name == table or name.startswith(table + "_") for table in FTS_TABLES)


def _optional_ident(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("component 識別碼格式無效")
    stripped = value.strip()
    return stripped or None


def _optional_version(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("version 格式無效")
    stripped = value.strip()
    return stripped or None


def _resolve_component(conn: sqlite3.Connection, component: str | None) -> str | None:
    if not component:
        return None
    row = conn.execute("SELECT id FROM components WHERE id=?", (component,)).fetchone()
    if row:
        return str(row[0])
    row = conn.execute(
        "SELECT component_id FROM aliases WHERE alias=? COLLATE NOCASE LIMIT 1",
        (component,),
    ).fetchone()
    if row:
        return str(row[0])
    return component


def _quote_match(tokens: list[str]) -> str:
    return " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens)


def _fts_ids(conn: sqlite3.Connection, table: str, tokens: list[str], component: str | None, limit: int, version: str | None = None) -> list[int]:
    if table not in FTS_TABLES or not tokens:
        return []
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'", (table,)).fetchone():
        return []
    sql = (
        f"SELECT {table}.rowid FROM {table} "
        f"JOIN chunks c ON c.id={table}.rowid "
        f"JOIN sources s ON s.id=c.source_id "
        f"WHERE {table} MATCH ?"
    )
    args: list = [_quote_match(tokens)]
    if component:
        sql += " AND s.component_id=?"
        args.append(component)
    if version:
        sql += " AND s.doc_version=?"
        args.append(version)
    sql += f" ORDER BY bm25({table}) LIMIT {int(limit)}"
    try:
        return [int(row[0]) for row in conn.execute(sql, args).fetchall()]
    except sqlite3.OperationalError:
        return []


def _search_rows(conn: sqlite3.Connection, tokens: list[str], component: str | None, version: str | None, limit: int):
    def candidates(doc_version):
        found = _fts_ids(conn, "chunks_fts", tokens, component, 40, doc_version)
        if not found:
            long_tokens = [token for token in tokens if len(token) >= 3]
            if long_tokens:
                found = _fts_ids(conn, "chunks_fts_trigram", long_tokens, component, 40, doc_version)
        if not found:
            found = _like_ids(conn, tokens, limit * 4, component, doc_version)
        return found
    # Filter version before candidate LIMIT; an exact-version document must not
    # disappear behind dozens of higher-scoring documents for another version.
    ids = candidates(version)
    if not ids and version:
        ids = candidates(None)
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    sql = _DOC_SQL + f" WHERE c.id IN ({placeholders})"
    args: list = list(ids)
    if component:
        sql += " AND p.id=?"
        args.append(component)
    rows = [dict(row) for row in conn.execute(sql, args).fetchall()]
    rows.sort(key=lambda row: ids.index(int(row["chunk_id"])) if int(row["chunk_id"]) in ids else 999)
    if version:
        exact = [row for row in rows if row["doc_version"] == version]
        if exact:
            return exact[:limit]
        return rows[:limit]
    return rows[:limit]


def _like_ids(conn: sqlite3.Connection, tokens: list[str], limit: int, component: str | None = None, version: str | None = None) -> list[int]:
    ids: list[int] = []
    component_sql = " AND s.component_id=?" if component else ""
    if version: component_sql += " AND s.doc_version=?"
    for token in tokens:
        pattern = "%" + token.replace(LIKE_ESCAPE, LIKE_ESCAPE + LIKE_ESCAPE).replace("%", LIKE_ESCAPE + "%").replace("_", LIKE_ESCAPE + "_") + "%"
        like_args: list = [pattern, LIKE_ESCAPE, pattern, LIKE_ESCAPE, pattern, LIKE_ESCAPE]
        sql = (
            "SELECT c.id FROM chunks c JOIN sources s ON s.id=c.source_id "
            "WHERE (c.heading LIKE ? ESCAPE ? OR c.summary_zh_tw LIKE ? ESCAPE ? OR c.keywords LIKE ? ESCAPE ?)"
            + component_sql
            + " LIMIT 20"
        )
        if component:
            like_args.append(component)
        if version: like_args.append(version)
        for row in conn.execute(sql, like_args).fetchall():
            if int(row[0]) not in ids:
                ids.append(int(row[0]))
            if len(ids) >= limit:
                return ids
        alias_sql = (
            "SELECT c.id FROM aliases a "
            "JOIN sources s ON s.component_id=a.component_id "
            "JOIN chunks c ON c.source_id=s.id "
            "WHERE a.alias LIKE ? ESCAPE ?"
            + component_sql
            + " LIMIT 8"
        )
        alias_args: list = [pattern, LIKE_ESCAPE]
        if component:
            alias_args.append(component)
        if version: alias_args.append(version)
        for row in conn.execute(alias_sql, alias_args).fetchall():
            if int(row[0]) not in ids:
                ids.append(int(row[0]))
            if len(ids) >= limit:
                return ids
    return ids


def _row_result(row, requested_version: str | None) -> dict:
    data = dict(row) if not isinstance(row, dict) else row
    body = str(data.get("summary_zh_tw") or data.get("body") or "")
    version = data.get("version") or ""
    if requested_version and data.get("doc_version") == requested_version:
        match_kind = "exact_version"
    elif requested_version:
        match_kind = "reference_only"
    else:
        match_kind = "version_unspecified"
    return {
        "chunk_id": int(data["chunk_id"] if "chunk_id" in data else data["id"]),
        "component": data.get("component") or "",
        "version": version,
        "doc_version": data.get("doc_version") or "",
        "title": (data.get("heading") or "")[:300],
        "snippet": body[:1500],
        "source_url": data.get("url") or "",
        "section_anchor": data.get("section_anchor") or "",
        "retrieved_at": data.get("retrieved_at") or "",
        "verification_status": data.get("verification_status") or "",
        "implementation_status": data.get("implementation_status") or "",
        "score": data.get("score"),
        "match_kind": match_kind,
    }


def _bounded(payload: dict) -> dict:
    if len(json.dumps(payload, ensure_ascii=False)) <= 20000:
        return payload
    def trim(value, chars, depth=0):
        if isinstance(value, str): return value[:chars]
        if depth > 8: return "[深層內容已省略]"
        if isinstance(value, list): return [trim(v, chars, depth + 1) for v in value[:10]]
        if isinstance(value, dict): return {str(k)[:100]: trim(v, chars, depth + 1) for k, v in list(value.items())[:50]}
        return value
    for chars in (8000, 4000, 2000, 1000, 400, 100):
        bounded = trim(payload, chars)
        bounded["truncated"] = True
        bounded["warnings"] = list(bounded.get("warnings") or []) + ["內容超過 20000 字元，已截短；請縮小檢索範圍。"]
        if len(json.dumps(bounded, ensure_ascii=False)) <= 20000:
            return bounded
    return {"available": True, "truncated": True, "reason": "內容過大，請縮小檢索範圍"}


_DOC_SQL = """SELECT c.id AS chunk_id, c.heading, c.body, c.summary_zh_tw, c.section_anchor,
                      c.implementation_status, s.url, s.retrieved_at, s.verification_status, s.doc_version,
                      p.id AS component_id, p.name AS component, p.version
               FROM chunks c
               JOIN sources s ON s.id=c.source_id
               JOIN components p ON p.id=s.component_id"""
