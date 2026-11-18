# Changelog

All notable changes are documented here. The project follows [Semantic Versioning](https://semver.org/);
during 0.x, minor versions may include breaking API changes.

## [Unreleased]

### Added
- Amendment generalisation: deleting/substituting words, "substituting X for Y", "shall be read as",
  "read as if ... were deleted", "deleted in its entirety", inserts after/before a clause, schedules
  replaced wholesale, imperative and letter-style instructions, "shall cease to apply", renumbering,
  replacement text on the following line, targets by clause heading, amended-and-restated documents
  (a new version superseding the original), and number-tolerant wording ("thirty (30) days" = "30 days").
- An amendment instruction whose target clause, heading, anchor or wording is not in the amended document
  is flagged for human review (verify reports `needs_human_review`) and never applied.
- Schedule-aware section numbers (`Schedule 2/1.1`).
- Hidden-text detection: PDF white/near-white, invisible, under-2-pt and off-page text; DOCX `w:vanish`,
  white and tiny runs. Flagged passages get a `HIDDEN:` warning, review flags and caveats, and are never
  sent to a model.
- Business-day calendars: "10 Business Days of the Effective Date" becomes a date, skipping weekends and
  holidays from `CLAIMTRACE_HOLIDAYS`.
- ICS export: `GET /documents/{id}/deadlines.ics` and `claimtrace report <id> --format ics`.
- Optional OCR for scanned PDF pages (`pip install 'claimtrace[ocr]'` plus Tesseract) with per-page
  confidence, an `OCR:` warning and caveats on low-confidence pages.
- DOCX tables kept as one passage per row (cells joined with ` | `, `table N, row M` locator on spans).
- Hash-chained review trail (migration 002): `GET /reviews/verify-chain`, `claimtrace reviews verify`.
- Hash-pinned `requirements.lock`; `make check`, `make lock`, `make audit`.

### Changed
- Extractor version `rules-0.2.0`. Passages with instruction-like text are no longer included in model
  prompts at all (previously only model items quoting them were dropped).
- DOCX paragraphs and tables are read in document order (tables were appended at the end).
- Modify amendments only change the base commitments that contain the old wording; inserts never mark an
  existing clause replaced.
- Deleting a document erases its review decisions' content in place instead of deleting the rows, so the
  review chain still verifies. Review rows can no longer be deleted directly.
- CI installs runtime dependencies with `--require-hashes`, checks the lockfile against `pyproject.toml`,
  and `pip-audit` is blocking. The Docker image installs from the lockfile.

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
