-- Knowledge DB schema v1. Built offline after official-source retrieval.
-- FTS uses external-content mode: rowid = chunks.id. Rebuild after load; read-only product has no triggers.

CREATE TABLE kb_meta(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE components(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  version TEXT,
  version_status TEXT NOT NULL CHECK(version_status IN ('pinned','unknown')),
  kind TEXT,
  platform TEXT,
  upstream_url TEXT,
  license_spdx TEXT,
  implementation_status TEXT NOT NULL CHECK(
    implementation_status IN ('official_implemented','project_implemented','project_proposed','unverified')
  )
);

CREATE TABLE sources(
  id TEXT PRIMARY KEY,
  component_id TEXT NOT NULL REFERENCES components(id),
  url TEXT NOT NULL,
  title TEXT,
  source_kind TEXT,
  doc_version TEXT,
  git_ref TEXT,
  retrieved_at TEXT NOT NULL,
  content_sha256 TEXT,
  language TEXT,
  license_text TEXT,
  redistribution TEXT,
  verification_status TEXT
);

CREATE TABLE chunks(
  id INTEGER PRIMARY KEY,
  stable_key TEXT UNIQUE NOT NULL,
  source_id TEXT NOT NULL REFERENCES sources(id),
  section_anchor TEXT,
  heading TEXT,
  body TEXT,
  summary_zh_tw TEXT,
  keywords TEXT,
  applicability_json TEXT,
  implementation_status TEXT,
  confidence TEXT,
  content_sha256 TEXT
);

CREATE TABLE recipes(
  id TEXT PRIMARY KEY,
  component_id TEXT NOT NULL REFERENCES components(id),
  title TEXT,
  goal TEXT,
  prerequisites_json TEXT,
  steps_json TEXT,
  input_schema_json TEXT,
  output_schema_json TEXT,
  example_text TEXT,
  expected_result TEXT,
  side_effects_json TEXT,
  network_requirements_json TEXT,
  mode_requirements_json TEXT,
  validation_status TEXT,
  applicability_json TEXT,
  known_limits TEXT
);

CREATE TABLE recipe_sources(
  recipe_id TEXT NOT NULL REFERENCES recipes(id),
  chunk_id INTEGER NOT NULL REFERENCES chunks(id),
  PRIMARY KEY(recipe_id, chunk_id)
);

CREATE TABLE compatibility(
  id TEXT PRIMARY KEY,
  component_a_id TEXT NOT NULL REFERENCES components(id),
  component_b_id TEXT NOT NULL REFERENCES components(id),
  relation TEXT,
  status TEXT NOT NULL CHECK(status IN ('verified','documented','unverified','incompatible')),
  constraints_json TEXT,
  evidence_summary TEXT
);

CREATE TABLE compatibility_sources(
  compatibility_id TEXT NOT NULL REFERENCES compatibility(id),
  chunk_id INTEGER NOT NULL REFERENCES chunks(id),
  PRIMARY KEY(compatibility_id, chunk_id)
);

CREATE TABLE aliases(
  alias TEXT NOT NULL,
  component_id TEXT NOT NULL REFERENCES components(id),
  language TEXT NOT NULL,
  PRIMARY KEY(alias, component_id, language)
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
  heading, body, summary_zh_tw, keywords,
  content='chunks', content_rowid='id', tokenize='unicode61'
);

CREATE VIRTUAL TABLE chunks_fts_trigram USING fts5(
  heading, body, summary_zh_tw, keywords,
  content='chunks', content_rowid='id', tokenize='trigram'
);
