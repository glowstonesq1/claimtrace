-- ClaimTrace schema v1. Objects are stored as validated JSON plus indexed columns.
CREATE TABLE documents (
  id TEXT PRIMARY KEY,
  checksum TEXT NOT NULL,
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE passages (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL,
  json TEXT NOT NULL
);
CREATE INDEX ix_passages_doc ON passages(document_id, ordinal);
CREATE TABLE objects (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,              -- commitment | claim | party | definition | amendment_instruction
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  section_number TEXT,
  json TEXT NOT NULL
);
CREATE INDEX ix_objects_doc_kind ON objects(document_id, kind);
CREATE TABLE edges (
  id TEXT PRIMARY KEY,
  src_id TEXT NOT NULL,
  dst_id TEXT NOT NULL,
  type TEXT NOT NULL,
  document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
  json TEXT NOT NULL
);
CREATE INDEX ix_edges_src ON edges(src_id);
CREATE INDEX ix_edges_dst ON edges(dst_id);
CREATE TABLE analysis_runs (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  idem_key TEXT NOT NULL,
  json TEXT NOT NULL
);
CREATE INDEX ix_runs_idem ON analysis_runs(idem_key);
CREATE TABLE answers (
  id TEXT PRIMARY KEY,
  json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE answer_documents (
  answer_id TEXT NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  PRIMARY KEY (answer_id, document_id)
);
CREATE TABLE verification_runs (
  id TEXT PRIMARY KEY,
  base_document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  other_document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE findings (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES verification_runs(id) ON DELETE CASCADE,
  json TEXT NOT NULL
);
-- Append-only: rows are never updated (design-review D7).
CREATE TABLE reviews (
  id TEXT PRIMARY KEY,
  target_kind TEXT NOT NULL,
  target_id TEXT NOT NULL,
  json TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE INDEX ix_reviews_target ON reviews(target_id, at);
CREATE TRIGGER reviews_no_update BEFORE UPDATE ON reviews
BEGIN SELECT RAISE(ABORT, 'reviews are append-only'); END;
-- Content-free record that a document existed (design-review D15).
CREATE TABLE tombstones (
  document_id TEXT PRIMARY KEY,
  checksum TEXT NOT NULL,
  deleted_at TEXT NOT NULL,
  reason TEXT NOT NULL,
  counts TEXT NOT NULL
);
-- Local record of every send to an LLM endpoint (design-review D14). No content.
CREATE TABLE egress_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id TEXT,
  host TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  purpose TEXT NOT NULL,
  at TEXT NOT NULL
);
