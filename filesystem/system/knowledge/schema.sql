-- Product contract for filesystem/system/knowledge/dependencies.sqlite
-- Populate this file's companion DB with a separate build process; this product only reads it.
-- Tokenizer choice is documented by the builder. Do not add executable schema beyond FTS.

CREATE TABLE kb_meta(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE components(
  id TEXT PRIMARY KEY, name TEXT, version TEXT, version_status TEXT,
  kind TEXT, platform TEXT, upstream_url TEXT, license_spdx TEXT,
  implementation_status TEXT
);

CREATE TABLE sources(
  id TEXT PRIMARY KEY, component_id TEXT REFERENCES components(id), url TEXT, title TEXT,
  source_kind TEXT, doc_version TEXT, git_ref TEXT, retrieved_at TEXT,
  content_sha256 TEXT, language TEXT, license_text TEXT,
  redistribution TEXT, verification_status TEXT
);

CREATE TABLE chunks(
  id INTEGER PRIMARY KEY, stable_key TEXT UNIQUE, source_id TEXT REFERENCES sources(id),
  section_anchor TEXT, heading TEXT, body TEXT, summary_zh_tw TEXT,
  keywords TEXT, applicability_json TEXT, implementation_status TEXT,
  confidence TEXT, content_sha256 TEXT
);

CREATE TABLE recipes(
  id TEXT PRIMARY KEY, component_id TEXT REFERENCES components(id), title TEXT, goal TEXT,
  prerequisites_json TEXT, steps_json TEXT, input_schema_json TEXT,
  output_schema_json TEXT, example_text TEXT, expected_result TEXT,
  side_effects_json TEXT, network_requirements_json TEXT,
  mode_requirements_json TEXT, validation_status TEXT,
  applicability_json TEXT, known_limits TEXT
);

CREATE TABLE recipe_sources(
  recipe_id TEXT REFERENCES recipes(id),
  chunk_id INTEGER REFERENCES chunks(id),
  PRIMARY KEY(recipe_id, chunk_id)
);

CREATE TABLE compatibility(
  id TEXT PRIMARY KEY, component_a_id TEXT REFERENCES components(id),
  component_b_id TEXT REFERENCES components(id),
  relation TEXT, status TEXT, constraints_json TEXT, evidence_summary TEXT
);

CREATE TABLE compatibility_sources(
  compatibility_id TEXT REFERENCES compatibility(id),
  chunk_id INTEGER REFERENCES chunks(id),
  PRIMARY KEY(compatibility_id, chunk_id)
);

CREATE TABLE aliases(
  alias TEXT, component_id TEXT REFERENCES components(id), language TEXT,
  PRIMARY KEY(alias, component_id, language)
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
  heading, body, summary_zh_tw, keywords, content='chunks', content_rowid='id', tokenize='unicode61'
);

CREATE VIRTUAL TABLE chunks_fts_trigram USING fts5(
  heading, body, summary_zh_tw, keywords, content='chunks', content_rowid='id', tokenize='trigram'
);
