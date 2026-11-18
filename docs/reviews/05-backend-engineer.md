# Backend engineer

## Top 3 concerns
- §6 `POST /documents/{id}/analyze` is "idempotent per (checksum, extractor version)" but never says sync or async. LLM extraction on a 100-page contract takes minutes; a sync request will time out behind any proxy and the Compose web container. Risk: duplicate runs on client retry, half-written commitments. There is no job/run entity in §5 (only `VerificationRun` appears, in §6).
- §3.3 and §5 key everything to `char_start/char_end` into "normalised document text", but the normalisation version is not stored. Any parser or normaliser upgrade changes offsets, which silently breaks every stored Span, Provenance, review decision and report. Quote verification (§10) then fails or, worse, passes against shifted text.
- §9 hard delete cascades across passages, commitments, edges, answers "citing it" and findings. Answers and findings span multiple documents and `ReviewDecision` targets them by polymorphic `target_id`/`target_kind`, so FKs cannot enforce this. Orphans or leaked text from deleted documents are likely, and the spec does not define whether a cross-document finding survives deletion of one side.

## Top 3 recommendations
- Make analyze async: return `202` with an `AnalysisRun(id, document_id, extractor_version, status, error)`. Run it in a single in-process worker (thread plus a SQLite-backed queue, no Celery). Enforce a unique index on (document_id, checksum, extractor_version) to get real idempotency, and poll via `GET /runs/{id}`.
- Store `normalizer_version` and a `text_sha256` on the document. Persist the normalised text once, never recompute it, and have Spans reference (document_id, text_sha256, start, end). Re-ingestion creates a new document version rather than mutating offsets in place.
- Use `PRAGMA foreign_keys=ON`, WAL, and `ON DELETE CASCADE` for document-owned rows. For cross-document objects add join tables (`answer_citations`, `finding_spans`, `review_targets`) so deletion is a query, not application logic. Test it with a table-by-table "no row mentions deleted doc id" assertion.

## Must-have v0.1 requirements
- Schema migrations from day one (a `schema_version` table plus numbered SQL files). A Docker volume with a v0.1 DB must open under v0.1.1.
- The error shape in §6 must be applied through exception handlers that also cover FastAPI's 422 validation errors and 500s. Add contract tests asserting that every route returns the shape.
- Dependency-injected `Store` and extractor, with an in-memory SQLite fixture. Include a `fake` LLM provider test for the quote-drop path.
- Upload handling: stream to disk with the size cap enforced during the stream, not after `await file.read()`.
- Compose with a named volume for the DB and uploads, a healthcheck on `/health`, and a non-root user.

## Defer (and why)
- Splitting into multiple packages (§10): the single distribution is right. Enforce import direction with an import-linter test instead.
- The in-memory token bucket rate limit: it is meaningless for a single local user and breaks under multiple workers. Keep it as a stub.
- Retention purge on startup: it is risky without a dry-run and audit log. Ship it after the cascade tests are solid.

## Failure modes to test
- Double-click analyze, or a retry after a timeout: exactly one run and one set of commitments.
- Delete a document mid-analysis: the run aborts cleanly, with no orphan rows.
- Delete the amendment while a finding cites both documents.
- Concurrent writes (SQLite `database is locked`) during analyze plus review POSTs.
- Re-upload of the same checksum, and of a different file with the same title and version label.
- Offset stability: CRLF, ligatures, NBSP and soft hyphens in PDFs; quote verification still matches after a restart.
