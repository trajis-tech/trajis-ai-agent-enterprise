import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from backend.knowledge import (
    get_dependency_doc,
    get_recipe,
    knowledge_status,
    search_dependency_docs,
)


SCHEMA = """
CREATE TABLE kb_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE components(
  id TEXT PRIMARY KEY, name TEXT, version TEXT, version_status TEXT,
  kind TEXT, platform TEXT, upstream_url TEXT, license_spdx TEXT,
  implementation_status TEXT
);
CREATE TABLE sources(
  id TEXT PRIMARY KEY, component_id TEXT, url TEXT, title TEXT,
  source_kind TEXT, doc_version TEXT, git_ref TEXT, retrieved_at TEXT,
  content_sha256 TEXT, language TEXT, license_text TEXT,
  redistribution TEXT, verification_status TEXT
);
CREATE TABLE chunks(
  id INTEGER PRIMARY KEY, stable_key TEXT UNIQUE, source_id TEXT,
  section_anchor TEXT, heading TEXT, body TEXT, summary_zh_tw TEXT,
  keywords TEXT, applicability_json TEXT, implementation_status TEXT,
  confidence TEXT, content_sha256 TEXT
);
CREATE TABLE recipes(
  id TEXT PRIMARY KEY, component_id TEXT, title TEXT, goal TEXT,
  prerequisites_json TEXT, steps_json TEXT, input_schema_json TEXT,
  output_schema_json TEXT, example_text TEXT, expected_result TEXT,
  side_effects_json TEXT, network_requirements_json TEXT,
  mode_requirements_json TEXT, validation_status TEXT,
  applicability_json TEXT, known_limits TEXT
);
CREATE TABLE recipe_sources(recipe_id TEXT, chunk_id INTEGER, PRIMARY KEY(recipe_id, chunk_id));
CREATE TABLE compatibility(
  id TEXT PRIMARY KEY, component_a_id TEXT, component_b_id TEXT,
  relation TEXT, status TEXT, constraints_json TEXT, evidence_summary TEXT
);
CREATE TABLE compatibility_sources(compatibility_id TEXT, chunk_id INTEGER, PRIMARY KEY(compatibility_id, chunk_id));
CREATE TABLE aliases(alias TEXT, component_id TEXT, language TEXT, PRIMARY KEY(alias, component_id, language));
CREATE VIRTUAL TABLE chunks_fts USING fts5(heading, body, summary_zh_tw, keywords, tokenize='unicode61');
"""


def _populate(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO components VALUES (?,?,?,?,?,?,?,?,?)",
        ("openrpa", "OpenRPA", "1.4.57.13", "pinned", "app", "windows",
         "https://github.com/open-rpa/openrpa", "MS-PL", "project_implemented"),
    )
    conn.execute(
        "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("s1", "openrpa", "https://docs.openiap.io/docs/openrpa/Offline.html", "Offline",
         "official", "1.4", "", "2026-09-08", "abc", "en", "", "ok", "verified"),
    )
    conn.execute(
        "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (1, "k1", "s1", "offline", "離線模式",
         "OpenRPA can run offline without wsurl. The product broker at 127.0.0.1:8771 is not an official OpenRPA REST API.",
         "OpenRPA 可離線。本產品 8771 不是官方 REST。", "broker,offline", "{}",
         "project_implemented", "high", "abc"),
    )
    conn.execute(
        "INSERT INTO chunks_fts(rowid, heading, body, summary_zh_tw, keywords) VALUES (?,?,?,?,?)",
        (1, "離線模式",
         "OpenRPA can run offline without wsurl. The product broker at 127.0.0.1:8771 is not an official OpenRPA REST API.",
         "OpenRPA 可離線。本產品 8771 不是官方 REST。", "broker,offline"),
    )
    conn.execute(
        "INSERT INTO recipes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("r-offline", "openrpa", "離線啟動", "不連雲端啟動", "[]", "[]", "{}", "{}", "", "流程可離線載入",
         "[]", "[]", "[]", "documented", "{}", "CLI 完成不等於流程完成"),
    )
    conn.execute("INSERT INTO recipe_sources VALUES (?,?)", ("r-offline", 1))
    conn.execute("INSERT INTO aliases VALUES (?,?,?)", ("OpenRPA", "openrpa", "en"))
    conn.execute(
        "INSERT INTO components VALUES (?,?,?,?,?,?,?,?,?)",
        ("n8n", "n8n", "2.34.6", "pinned", "app", "windows",
         "https://github.com/n8n-io/n8n", "unknown", "official_implemented"),
    )
    conn.execute(
        "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("s2", "n8n", "https://docs.n8n.io/", "n8n docs",
         "official", "2.34.6", "", "2026-09-08", "def", "en", "", "ok", "verified"),
    )
    conn.execute(
        "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (2, "k2", "s2", "offline-nodes", "n8n offline custom nodes",
         "n8n can load custom nodes offline via N8N_CUSTOM_EXTENSIONS.",
         "n8n 可離線載入私有節點。", "offline,nodes", "{}",
         "project_implemented", "high", "def"),
    )
    conn.execute(
        "INSERT INTO chunks_fts(rowid, heading, body, summary_zh_tw, keywords) VALUES (?,?,?,?,?)",
        (2, "n8n offline custom nodes",
         "n8n can load custom nodes offline via N8N_CUSTOM_EXTENSIONS.",
         "n8n 可離線載入私有節點。", "offline,nodes"),
    )
    conn.commit()
    conn.close()


class KnowledgeReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "dependencies.sqlite"
        _populate(self.path)

    def test_missing_db_is_explicit(self):
        missing = Path(self.tmp.name) / "absent.sqlite"
        status = knowledge_status(missing)
        self.assertFalse(status["available"])
        self.assertIn("尚未匯入", status["reason"])
        self.assertEqual(search_dependency_docs(missing, "OpenRPA")["results"], [])

    def test_search_and_recipe_are_offline(self):
        hits = search_dependency_docs(self.path, "OpenRPA 8771")
        self.assertTrue(hits["available"])
        self.assertEqual(hits["results"][0]["chunk_id"], 1)
        self.assertEqual(hits["results"][0]["match_kind"], "version_unspecified")
        self.assertIn("不是官方 REST", hits["results"][0]["snippet"])
        doc = get_dependency_doc(self.path, 1)
        self.assertTrue(doc["found"])
        recipe = get_recipe(self.path, "r-offline")
        self.assertEqual(recipe["recipe"]["id"], "r-offline")
        self.assertEqual(recipe["recipe"]["sources"][0]["chunk_id"], 1)

    def test_version_mismatch_is_labeled_reference_only(self):
        hits = search_dependency_docs(self.path, "offline", version="9.9.9")
        self.assertEqual(hits["results"][0]["match_kind"], "reference_only")
        self.assertTrue(hits["warnings"])

    def test_installed_version_is_not_document_evidence(self):
        hits = search_dependency_docs(self.path, "offline", component="OpenRPA", version="1.4.57.13")
        self.assertEqual(hits["results"][0]["match_kind"], "reference_only")
        exact = search_dependency_docs(self.path, "offline", component="OpenRPA", version="1.4")
        self.assertEqual(exact["results"][0]["match_kind"], "exact_version")
        self.assertEqual(exact["results"][0]["doc_version"], "1.4")

    def test_document_body_and_large_recipe_are_bounded(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE chunks SET body=? WHERE id=1", ("detail " * 400 + "THE_END",))
            conn.execute("UPDATE recipes SET steps_json=?", (json.dumps(["step" * 10000] * 20),))
        conn.close()
        doc = get_dependency_doc(self.path, 1)
        self.assertIn("THE_END", json.dumps(doc))
        recipe = get_recipe(self.path, "r-offline")
        self.assertLessEqual(len(json.dumps(recipe, ensure_ascii=False)), 20000)
        self.assertTrue(recipe.get("truncated"))

    def test_fts_metacharacters_do_not_crash(self):
        for query in ('" OR 1=1', "()", "*", "n8n-nodes", "依賴"):
            result = search_dependency_docs(self.path, query)
            self.assertIn("results", result)

    def test_readonly_rejects_writes(self):
        from backend.knowledge import _open, _assert_schema
        with _open(self.path) as conn:
            _assert_schema(conn)
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("INSERT INTO aliases VALUES ('x','openrpa','zh')")

    def test_component_filter_and_alias(self):
        openrpa = search_dependency_docs(self.path, "offline", component="OpenRPA")
        self.assertEqual([item["chunk_id"] for item in openrpa["results"]], [1])
        n8n = search_dependency_docs(self.path, "offline", component="n8n")
        self.assertEqual([item["chunk_id"] for item in n8n["results"]], [2])
        blank = search_dependency_docs(self.path, "offline", component="   ")
        self.assertGreaterEqual(len(blank["results"]), 2)


class ImportedKnowledgeTests(unittest.TestCase):
    def test_product_db_answers_critical_questions(self):
        path = Path(__file__).resolve().parents[1] / "filesystem" / "system" / "knowledge" / "dependencies.sqlite"
        if not path.is_file():
            self.skipTest("dependencies.sqlite 尚未匯入")
        status = knowledge_status(path)
        self.assertTrue(status["available"], status)
        self.assertGreaterEqual(int(status["chunks"]), 10)
        hits = search_dependency_docs(path, "OpenRPA 8771")
        blob = " ".join(item.get("snippet") or "" for item in hits["results"])
        self.assertIn("8771", blob)
        self.assertTrue("不是" in blob or "沒有" in blob)
        aliased = search_dependency_docs(path, "offline", component="OpenRPA")
        self.assertTrue(aliased["results"])
        self.assertTrue(all(item["component"] == "OpenRPA" for item in aliased["results"]))
        recipe = get_recipe(path, "r-openrpa-offline")
        self.assertTrue(recipe.get("found"))
        self.assertTrue(recipe["recipe"]["sources"])


if __name__ == "__main__":
    unittest.main()
