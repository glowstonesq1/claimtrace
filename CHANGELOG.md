# Changelog

All notable changes are documented here. The project follows [Semantic Versioning](https://semver.org/);
during 0.x, minor versions may include breaking API changes.

## [0.1.0] — 2026-11-18

### Added
- Ingestion of PDF (text layer), DOCX, Markdown and TXT in a resource-limited subprocess, with type, size,
  active-content and archive checks; scanned-PDF and prompt-injection warnings; optional SSRF-safe URL
  ingestion (off by default).
- Rules-based extraction of parties, definitions, commitments (type, modality, parties, deadlines,
  conditions, exceptions, references), amendment instructions and evidence statements, with categorical
  confidence and review flags.
- Amendment application that keeps original clauses and marks them replaced or deleted.
- Provenance graph in SQLite with append-only reviews, run manifests, tombstones and an egress log.
- Grounded Q&A with verified quotes, amendment- and evidence-aware answers, and an exact not-found response.
- Cross-document verification (amendment, evidence, version and general modes) with typed comparisons.
- Optional OpenAI-compatible model provider (incl. Ollama) with schema validation, quote verification and a
  per-document egress gate.
- REST API with OpenAPI docs, structured errors, security middleware, rate limiting and exports
  (JSON, Markdown, HTML, CSV).
- Accessible React UI (library, register, ask, verify, review).
- Evaluation suite: 140-case core set, 46-case sealed holdout, runner with bootstrap CIs, published baselines.
- Docker Compose deployment, CI, documentation.
