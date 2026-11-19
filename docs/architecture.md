# ClaimTrace architecture

Describes commit 1899c3c.

This document describes how the code is organised and how a request moves through it. It
describes the code as it is. Where the code differs from `docs/product-spec.md` or
`docs/design-review.md`, the difference is stated. ClaimTrace is a document-review aid, not
legal advice.

## 1. Module map

There is one Python distribution, `claimtrace` (version 0.1.0). `pyproject.toml` maps the
monorepo directories onto subpackages with `package-dir`:

| Directory | Import name | Role |
|---|---|---|
| `packages/__init__.py` | `claimtrace` | Holds `__version__`. |
| `packages/core/` | `claimtrace.core` | Pydantic models and enums (`models.py`), SQLite `Store` and migrations (`store.py`, `migrations/*.sql`), text normalisation, quote finding, tokenising and the injection heuristic (`text.py`), settings from environment variables (`config.py`). |
| `packages/ingestion/` | `claimtrace.ingestion` | File-type allowlist and parsers (`parsers.py`), subprocess sandbox (`sandbox.py`, `worker.py`), segmentation into passages and storage (`pipeline.py`), SSRF-hardened URL fetch (`url.py`). |
| `packages/extraction/` | `claimtrace.extraction` | Rules extractor (`rules.py`, `patterns.py`), amendment instruction parser (`amendments.py`), cross-document amendment application (`apply.py`), optional LLM extractor (`llm.py`), run orchestration (`analyze.py`). |
| `packages/retrieval/` | `claimtrace.retrieval` | BM25 over passages, query expansion table, per-term groups for coverage. Lexical only. |
| `packages/verification/` | `claimtrace.verification` | Question answering (`ask.py`), document-pair verification (`verify.py`), typed field comparison (`compare.py`), report and CSV export (`report.py`). |
| `packages/integrations/` | `claimtrace.integrations` | `LLMProvider` protocol, `OpenAICompatible` HTTP adapter, `FakeProvider` for tests. |
| `packages/evaluation/` | `claimtrace.evaluation` | Eval runner used by `claimtrace eval`. |
| `packages/cli/` | `claimtrace.cli` | `claimtrace` command: `serve`, `ingest`, `list`, `ask`, `verify`, `report`, `delete`, `eval run`, `eval report`. |
| `apps/api/` | `claimtrace.api` | FastAPI app (`main.py`) and the built web UI under `static/`. |
| `apps/web/` | (not Python) | React + Vite SPA source. `npm run build` output is copied to `apps/api/static` and served by FastAPI. No Node process at runtime (D19). |

Import direction (checked by reading imports at this commit; no test enforces it):

```
core  <-  ingestion
core  <-  integrations  <-  extraction
core  <-  retrieval
core, extraction, integrations, retrieval  <-  verification
everything  <-  evaluation, cli, api
```

`core` imports nothing else from `claimtrace`. `verification` imports
`extraction.patterns` (the recognisers) and `extraction.rules.EXTRACTOR_VERSION`.

The web UI has four destinations, matching D17: Documents (library), Document, Ask, and
"Check documents" (Verify). Routing is hash-based in `apps/web/src/App.tsx`. Plain-language
labels for API enums are in `apps/web/src/labels.ts` (D18).

## 2. Request flows

All flows go through `SecurityMiddleware` first (section 6). Every route uses the one
`Store` held on `app.state.store`.

### 2.1 Upload

```
Client            API /documents          ingestion.pipeline        sandbox worker        Store
  | POST file ---->|                          |                         |                    |
  |                | _read_capped (20 MB) --->|                         |                    |
  |                |                          | detect_kind (ext+magic) |                    |
  |                |                          | find_by_checksum ------------------------------>|
  |                |                          |<-- existing doc? return it (dedupe) -----------|
  |                |                          | parse_sandboxed ------->| parse() under      |
  |                |                          |                         | rlimits, JSON out  |
  |                |                          |<------ RawDoc ----------|                    |
  |                |                          | segment(): normalise each block, offsets   |
  |                |                          | injection scan, scanned warning, amends    |
  |                |                          | lookup by title, Document(text_sha256)     |
  |                |                          | add_document(doc, text, passages) -------->|
  |                | apply_amendments(store) ------------------------------------------------>|
  |<-- 201 Document|                          |                         |                    |
```

If the upload names `amends_document_id`, that document must exist. If the Markdown front
matter has `amends: <title>`, ingestion links to an already uploaded document whose title
matches exactly (case-insensitive); otherwise it adds a warning. A `url` form field is
accepted only when `CLAIMTRACE_ALLOW_URL_INGESTION=true`; otherwise 403
`url_ingestion_disabled`.

### 2.2 Analyze (background run)

```
Client           API /documents/{id}/analyze      extraction.analyze           Store
  | POST ------->| start_run(doc, provider) ------>| idem_key -> find_run ------->|
  |              |                                 |<-- non-failed run? reuse ----|
  |              |                                 | else new run (queued) ------>|
  |<-- 202 {run, poll:/runs/{id}}                  |                              |
  |              | BackgroundTasks: execute_run -->| status running, doc analyzing|
  |              |                                 | extract_rules(doc, passages) |
  |              |                                 | [extract_llm if provider]    |
  |              |                                 | replace_extraction (atomic) ->|
  |              |                                 | apply_amendments(store) ---->|
  |              |                                 | counts + run_manifest, done  |
  | GET /runs/{id} ----------------------------------------------------------->|
```

### 2.3 Ask

```
Client        API /ask        verification.ask                       Store
  | POST ---->| answer_question(question, document_ids, provider)       |
  |           |   load docs, passages, commitments, claims, edges <------|
  |           |   route intent: due-soon | changed | evidence-gaps |      |
  |           |                 conflicts | list | lookup               |
  |           |   lookup: BM25 -> weighted coverage >= 0.5 ->            |
  |           |     answer-type check -> [LLM composer] -> commitment,   |
  |           |     amendment and evidence-conflict checks               |
  |           |   add scope caveat; verify every citation against text ->|
  |           |   drop unverified; no support -> not-found sentence      |
  |           |   save_answer ------------------------------------------>|
  |<-- Answer |                                                          |
```

### 2.4 Verify

```
Client       API /verify      verification.verify                 compare            Store
  | POST --->| verify_documents(base, other)                          |                  |
  |          |   _mode(): amendment | evidence | version | general    |                  |
  |          |   collect commitments / claims / sentences <-------------------------------|
  |          |   pair candidates by overlap thresholds                 |                  |
  |          |   judge(commitment, candidates) --------------------->| typed fields     |
  |          |   Finding(verdict, severity, action, sufficiency)       |                  |
  |          |   save_verification (run + findings) ------------------------------------>|
  |<-- VerificationRun                                                |                  |
```

`/verify` takes only the two document IDs. The product spec lists an optional `mode`; the
code always infers the mode. `/ask` for "evidence gaps" and "conflicts" calls
`verify_documents` internally, so those questions also store verification runs.

## 3. The two seams

There are two abstractions with more than one implementation path. Everything else is
concrete.

| Seam | Where | Implementations at this commit |
|---|---|---|
| `Store` | `core/store.py` | SQLite only. All reads and writes of documents, passages, objects, edges, runs, answers, verifications, reviews, tombstones and the egress log go through it. |
| `LLMProvider` | `integrations/llm.py` (a `Protocol`: `name`, `model`, `host`, `external`, `complete_json(system, user) -> dict`) | `None` (rules only, the default), `OpenAICompatible` (OpenAI, Ollama `/v1`, vLLM, LM Studio, llama.cpp server), `FakeProvider` (tests). |

Why there are no other seams yet (design-review §6.4, D11): no Postgres, graph-database or
vector-store adapter exists, and building an interface with a single implementation would be
speculative. Retrieval is a concrete BM25 class; extractors are plain functions called from
`execute_run`. `Store` is a concrete class, not an abstract base; a second backend would
need the same method set.

Provider selection (`provider_from_settings`): `CLAIMTRACE_LLM_PROVIDER` of `""`, `rules`
or `none` gives no provider; `openai`, `ollama` or `openai-compatible` require
`CLAIMTRACE_LLM_BASE_URL` (Ollama defaults to `http://localhost:11434/v1`) and
`CLAIMTRACE_LLM_MODEL`. A host other than `localhost`, `127.0.0.1`, `::1`, `ollama` or
`host.docker.internal` is external and then needs the per-document `allow_external_llm`
flag (D14). The adapter sends `temperature: 0` and `response_format: json_object`, retries
twice on errors with backoff, and never echoes the response body in errors.

## 4. Sandboxed parsing

`parse_sandboxed` runs `python -I -m claimtrace.ingestion.worker` as a subprocess. The
worker reads the kind on the first stdin line and the file bytes after it, and writes a JSON
`RawDoc` or `{ok: false, code, message}` to stdout.

| Limit | Value |
|---|---|
| CPU (`RLIMIT_CPU`) | 30 s |
| Address space (`RLIMIT_AS`) | 1 GiB |
| Open files (`RLIMIT_NOFILE`) | 64 |
| Wall clock (`subprocess` timeout) | 60 s |
| Upload size | 20 MB (checked while streaming and again in `ingest_bytes`) |

Limits are applied with `preexec_fn`, so they are not applied on Windows. A non-zero exit,
empty output or timeout becomes `IngestError("resource_limit")`. Parser exceptions other
than `IngestError` and `MemoryError` become `parse_failed` with a fixed message, so parser
internals (which may contain document text) are not returned.

Checks inside the parsers (D12):

- Type: extension allowlist (`pdf`, `docx`, `md`/`markdown`, `txt`/`text`) and magic
  bytes must agree. Text must be UTF-8 without NUL bytes in the first 4 KiB.
- DOCX: rejects macro, OLE, ActiveX and embedded parts; nested archives; members with a
  compression ratio over 100 and more than 1 MB uncompressed; more than 50 MB total
  uncompressed; any XML with DTD or entities (`defusedxml`); external relationships to
  templates, OLE objects, frames, subdocuments. Warns that automatic numbering is lost.
- PDF: rejects `/JavaScript`, `/JS`, `/Launch`, `/EmbeddedFile`, `/RichMedia`, `/XFA`
  byte markers, encrypted files, Names-tree JavaScript or embedded files, and more than 500
  pages. Fewer than 40 text characters per page adds a `SCANNED:` warning.
- PDF hidden text (v0.2): while extracting each page, text drawn white or near-white, in
  render mode 3, under 2 pt, or outside the media box is recorded on the block and later on the
  passage (`hidden_text`); DOCX runs with `w:vanish`, white colour or under 2 pt likewise. See
  [security.md](security.md).
- DOCX body order and tables (v0.2): paragraphs and tables are read in document order. Each table
  row becomes one block/passage: non-empty cells joined with `" | "` (a horizontally merged cell
  appears once; a literal `" | "` inside a cell becomes `" / "`), with `locator="table N, row M"`
  on the passage and on every span quoted from it. Rows take the section number of the clause they
  follow. The rules extractor reads each cell as its own region, so quotes never cross a cell
  boundary and still verify; a commitment with no timing of its own takes a date or relative
  deadline from another cell in the same row, with a caveat saying so.
- OCR (v0.2, optional extra `pip install 'claimtrace[ocr]'` plus the `tesseract` binary): pages
  with fewer than 40 text characters are rendered with pypdfium2 at 300 dpi and read with
  Tesseract (`ingestion/ocr.py`). OCR text replaces a page's text only if it is longer. Each OCR
  passage stores the page's mean word confidence (`Passage.ocr_confidence`); the document gets an
  `OCR:` warning listing pages and confidences, and items from pages under 70/100 are capped at
  medium confidence, need review and carry a caveat. Without the binary or packages, or with
  `CLAIMTRACE_OCR=off`, scanned PDFs get exactly the v0.1 `SCANNED:` warning; an OCR failure keeps
  the text layer and adds a warning. The engine is a seam (`OcrFunc(pdf_bytes, pages) ->
  {page: (text, confidence)}`) passed as `IngestOptions(ocr=...)` (a module-level function; default:
  the installed engine). In the sandbox, the text layer is parsed first under the usual limits; OCR
  then runs as a separate sandboxed step (`sandbox.ocr_sandboxed`) with a per-page budget
  (`OCR_PAGE_SECONDS`, plus start-up time, within `OCR_TOTAL_SECONDS`). A page that overruns or
  crashes is skipped with an `OCR: ... time limit` / `OCR failed` warning and the document is kept
  (with `SCANNED:` if little text remains), so a long scan is never rejected for OCR time.
- After parsing, `pipeline.ingest_bytes` adds an `INJECTION:` warning listing sections whose
  text matches `looks_like_injection`, and a `SCANNED:` warning if no passages were found.

`IngestOptions(sandbox=False)` parses in-process; tests and the eval use it.

## 5. Background analysis runs and the idempotency key

`POST /documents/{id}/analyze` returns 202 with the run and a poll URL (D10). The run is
executed by FastAPI `BackgroundTasks` after the response is sent (a sync function, so it
runs in the thread pool). There is no queue and no worker process.

Idempotency key (`analyze.idem_key`):

```
{document_id}:{text_sha256}:{EXTRACTOR_VERSION}:{provider.name}:{provider.model}   # or ":rules"
```

This differs from D10 and the product spec, which key on (document, text hash, extractor
version) or (checksum, extractor version): the code also includes the provider and model.

`Store.find_run` returns the newest run for the key whose status is not `failed`. So:

- a `queued`, `running` or `done` run is returned again and no new task starts;
- a failed run is ignored and a new run is created and started;
- re-analysing an unchanged document with the same extractor and model is a no-op that
  returns the earlier `done` run.

The API also checks `run.status == "failed"` before scheduling, but `find_run` never returns
a failed run, so that branch is not reached. If the process stops while a run is `queued`
or `running`, that run stays in that state and blocks a new run for the same key.

`execute_run` writes the run as `running` and the document as `analyzing`, then calls
`extract_rules`, optionally `extract_llm`, swaps all objects and per-document edges in one
transaction (`replace_extraction`), recomputes amendments across all documents, and stores
counts and a run manifest (`claimtrace_version`, `document_checksum`, `text_sha256`,
`normalizer_version`, `extractor_version`, `model`, `provider`, `endpoint_host`,
`prompt_version`). D8 also lists a parser version; no parser version is recorded. On an
exception the run is `failed`; the stored error is the exception class name only, except
for `EgressNotAllowed`, whose message is kept.

`POST /samples` ingests the four bundled sample documents and runs analysis synchronously.
The CLI `ingest` command and `analyze_document` are also synchronous.

## 6. Security middleware order

`create_app` refuses to start if the bind host is not loopback and no
`CLAIMTRACE_API_TOKEN` is set, unless `CLAIMTRACE_CONTAINER_MODE` is on (Docker binds
`0.0.0.0` and compose publishes on `127.0.0.1`).

One custom middleware, `SecurityMiddleware`, does all checks, in this order:

| Step | Check | Failure |
|---|---|---|
| 1 | Host header must be loopback, `testserver`, or in `CLAIMTRACE_ALLOWED_HOSTS`. Only when the server is loopback or container mode **and** no token is set. | 400 `bad_host` |
| 2 | For methods other than GET/HEAD/OPTIONS: if an `Origin` header is present it must equal `scheme://Host` or be in `CLAIMTRACE_ALLOWED_ORIGINS`. A missing `Origin` is allowed. | 403 `bad_origin` |
| 3 | If a token is configured: `Authorization: Bearer <token>` or a `ct_token` cookie, compared with `hmac.compare_digest`. Exempt: `/health`, `/`, `/assets*`, `/favicon*`. | 401 `unauthorized` |
| 4 | Token-bucket rate limit per client IP, `CLAIMTRACE_RATE_LIMIT` per minute (default 120). | 429 `rate_limited` |
| 5 | Call the route. | |
| 6 | Set `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, and a `Content-Security-Policy` (not on `/docs`, `/redoc`, `/openapi*`). | |
| 7 | Log an `http` event with method, route template, status and duration. | |

There is no `CORSMiddleware`. No `Access-Control-Allow-*` headers are sent, so browsers
block cross-origin reads; D13's "CORS allows the UI origin only" holds only in the sense
that the UI is same-origin. No code in the repository sets the `ct_token` cookie.

Error handlers return `{"error": {code, message, details}}` and never echo request values
or document text. Logs are JSON lines with IDs, counts and durations only.

## 7. Extension points

### 7.1 Add a parser

1. In `ingestion/parsers.py`, add the extension and magic-byte check to `detect_kind` and
   return a new kind string.
2. Write `parse_<kind>(data) -> RawDoc`. Return ordered `Block(text, page, heading)`;
   put safety rejections in `IngestError(code, message)` with a fixed message.
3. Dispatch it in `parse()`. The worker and sandbox need no change.
4. If the format can carry a title, version, type or amended-document title, fill the
   `RawDoc` fields; `pipeline.ingest_bytes` uses them.
5. Map any new `IngestError` code to an HTTP status in the `IngestError` handler in
   `apps/api/main.py` (unknown codes become 422).
6. Add malicious-input tests next to `tests/test_files_security.py`.

Do not normalise inside the parser: `segment()` normalises each block and computes offsets,
and offsets are only stable if all text goes through `core.text.normalize`.

### 7.2 Add an extractor

There is no plugin registry. An extractor is a function called from
`extraction/analyze.execute_run`:

1. Return model objects (`Commitment`, `Claim`, `Party`, `Definition`,
   `AmendmentInstruction`) whose `provenance.span` comes from `rules.make_span`, so offsets
   index the stored text. Locate quotes with `core.text.find_quote`; never trust offsets
   from a model.
2. Set `provenance.extraction_method`, `extractor_version` and, for a model,
   `model`, `endpoint_host`, `prompt_version`.
3. Append results to the `ExtractionResult` before `store.replace_extraction`. Commitments
   added after `extract_rules` returns (as the LLM extractor's are) get no graph edges.
4. If the output changes, bump `EXTRACTOR_VERSION` (it is part of the idempotency key and
   the run manifest).
5. Any new object kind needs an entry in `Store._KIND`.
