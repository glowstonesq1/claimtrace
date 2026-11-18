# ClaimTrace — Product Specification

Status: v0.1 draft for design review · Written 2026-11-18 · Owner: maintainers

> ClaimTrace is a document-review aid. It is **not legal advice**, does not decide
> what is true, and never acts on documents on the user's behalf.

## 1. Problem statement

People who manage vendor contracts, audits, and projects must answer questions
like "did we promise delivery by March 31?" or "did the amendment change the
payment terms?". Today they do this by reading PDFs side by side. The failure
modes are concrete:

- An obligation buried in clause 14.3 is missed; a deadline passes.
- An amendment silently changes a term, and the team keeps working from the
  original.
- An audit report says "control implemented", and nobody checks it against the
  evidence the contract required.
- Generic AI chat tools answer confidently with no quote, or with a quote that
  is not in the document.

The gap is not "search" or "chat". It is **an auditable register of who owes
what to whom, by when, under which conditions, with every entry linked to the
exact source text**, plus a way to check documents against each other.

## 2. Personas and jobs to be done

| Persona | Job to be done | What "good" looks like |
|---|---|---|
| Ops / business owner (non-technical) | "Tell me what we and the vendor must do, and by when." | A deadline list they can trust, each with the quote. |
| Procurement / compliance / audit | "Check that commitments are met and evidenced." | Findings with severity, source locations, and a review trail. |
| Legal-adjacent reviewer | "Show me what changed between versions." | Clause-level diff with superseded/amended status. |
| Project manager | "What is due in the next 30 days, and what blocks it?" | Deadline view with conditions and dependencies. |
| Researcher / policy analyst | "Does this report support this claim?" | Support / contradict / not-addressed verdict with quotes. |
| Developer | "Build trustworthy document-AI features." | Typed API, provenance on every object, reproducible evals. |

## 3. MVP scope (v0.1)

**In scope**

1. Ingest PDF (text layer), DOCX, Markdown, TXT. URL ingestion behind a
   disabled-by-default flag with SSRF protections.
2. Per-document metadata: title, version label, doc type, source, author,
   upload time, SHA-256 checksum, page count, section map. Documents can be
   linked as `amends` / `supersedes` another document.
3. Passage segmentation that keeps page number, section heading/number, and
   character offsets into the normalised document text.
4. Commitment extraction (rules baseline + optional LLM extractor), with
   Pydantic-validated output and verbatim-quote verification.
5. Party, definition, and date/deadline extraction.
6. Provenance graph (nodes + typed edges) in SQLite.
7. Grounded Q&A (`/ask`) with answer status, quotes, locations, graph path,
   caveats, follow-ups.
8. Cross-document verification (`/verify`) for a pair of documents.
9. Human review on commitments, answers, and findings.
10. Report export: Markdown, JSON, print-ready HTML.
11. Web UI covering library, commitment register, ask, verify, review, report.
12. Evaluation suite + runner + published baseline.

**Explicit non-goals (v0.1)**

- Legal advice, legal sufficiency opinions, or clause "risk scores".
- OCR of scanned PDFs (detected and flagged; OCR is v0.2).
- Multi-user accounts, SSO, RBAC (auth hook only).
- Postgres / graph DB / vector DB adapters (interfaces only where a second
  adapter is planned; see §10).
- Automatic notices, emails, calendar entries, or contract edits.
- Public web fact-checking or social media scanning.
- Dense-embedding retrieval (lexical BM25 first; embeddings in v0.2 once the
  eval shows where lexical retrieval fails).

## 4. User journeys

**J1 — First look at a vendor contract.** Upload `msa.pdf` → status shows
"parsed, 12 pages, 41 passages" → "Analyze" → commitment register lists 18
items grouped by party, each with type, deadline, confidence, and a "Review"
badge on low-confidence ones → clicking an item shows the exact quote
highlighted in its passage with page and section.

**J2 — Ask a question.** "Did the vendor promise delivery by March 31?" →
answer: *Stated in document* · confidence *high* · quote "Vendor shall deliver
the Phase 1 system no later than March 31, 2026" (MSA v1, §4.2, p.3) · graph
path `Vendor —made_by→ C-12 —requires→ Deadline 2026-03-31` · caveat
"Amendment 1 §2 changes this date (see follow-up)" · follow-ups.

**J3 — Not found.** "What is the liability cap?" with no such clause →
"I could not find support for this in the uploaded documents." + the closest
passages that were checked, labelled as *not supporting*.

**J4 — Contract vs amendment.** Select MSA v1 and Amendment 1 → verify →
findings board: *contradicted* (delivery date changed 2026-03-31 → 2026-05-15,
severity high, action "confirm which date governs; update the register"),
*consistent* items collapsed, *needs_human_review* where matching was weak.

**J5 — Review and export.** Reviewer accepts/rejects findings, adds notes,
marks resolved → exports Markdown / HTML report with the review trail and the
not-legal-advice notice.

## 5. Data model (summary — full detail in `docs/data-model.md`)

All IDs are stable strings (`doc_…`, `psg_…`, `cmt_…`). All extracted objects
carry a `Provenance` record.

```
Document(id, title, version_label, doc_type, source, author, uploaded_at,
         checksum_sha256, page_count, status, tags[], related_to?, relation?)
Passage(id, document_id, ordinal, page, section_number, section_title,
        char_start, char_end, text)
Span(document_id, passage_id, char_start, char_end, quote, page, section)
Provenance(source_document_id, document_version, span, extraction_method,
           model, prompt_version, extracted_at, confidence, review_status)
Party(id, name, aliases[], role)            # e.g. "Vendor" = "Acme Ltd"
Definition(id, term, definition_text, provenance)
Commitment(id, document_id, text, type, obliging_party, beneficiary_party,
           action, deadline{raw, date?, kind}, conditions[], exceptions[],
           status, provenance, needs_review, review_reasons[])
Claim(id, document_id, text, claim_type, subject, provenance, needs_review)
Edge(id, src_id, dst_id, type, provenance)
Answer(id, question, status, answer_text, confidence, citations[Span],
       graph_path[], caveats[], follow_ups[], review_status, created_at)
Finding(id, run_id, verdict, subject_id, subject_text, supporting[Span],
        conflicting[Span], explanation, severity, recommended_action,
        review_status)
ReviewDecision(id, target_id, target_kind, decision, note, reviewer, at)
```

Enumerations:

- `CommitmentType`: obligation, entitlement, prohibition, condition, deadline,
  consequence, service_level
- `CommitmentStatus`: stated, amended, superseded, open, fulfilled, disputed,
  unknown
- `Confidence`: high, medium, low, unknown — **categorical, rule-derived**, never
  a fabricated probability (see `docs/commitment-model.md`).
- `AnswerStatus`: stated, implied, contradicted, not_addressed, ambiguous,
  needs_human_review
- `Verdict`: consistent, contradicted, partially_supported, not_addressed,
  ambiguous, needs_human_review
- `EdgeType`: made_by, owed_to, requires, conditioned_on, amends, supersedes,
  supports, contradicts, qualifies, depends_on, duplicates, references,
  evidence_for
- `ReviewStatus`: unreviewed, accepted, rejected, needs_evidence, resolved

## 6. API design

REST, JSON, FastAPI-generated OpenAPI at `/docs`. Errors use one shape:
`{"error": {"code": "unsupported_file_type", "message": "...", "details": {}}}`.
Every route goes through an `authorize(request)` dependency (no-op in v0.1,
replaceable) and a `rate_limit(request)` dependency (in-memory token bucket).

| Method & path | Purpose |
|---|---|
| `POST /documents` | Upload file (multipart) or `{url}` if URL ingestion enabled. Returns `Document`. |
| `GET /documents` | List with versions, tags, status. |
| `GET /documents/{id}` | Metadata + passages. |
| `DELETE /documents/{id}` | Hard delete document and everything derived from it. |
| `POST /documents/{id}/analyze` | Run extraction; idempotent per (checksum, extractor version). |
| `GET /documents/{id}/commitments` | Filter by `type`, `party`, `status`, `due_before`, `needs_review`. |
| `GET /documents/{id}/claims` | Claims list. |
| `GET /documents/{id}/graph` | Nodes + edges with provenance. |
| `POST /ask` | `{question, document_ids?}` → `Answer`. |
| `GET /answers/{id}` | Stored answer. |
| `POST /answers/{id}/review` | Review decision. |
| `POST /verify` | `{base_document_id, other_document_id, mode?}` → `VerificationRun` with findings. |
| `POST /findings/{id}/review`, `POST /commitments/{id}/review` | Review decisions. |
| `GET /documents/{id}/report?format=md|json|html` | Export. |
| `GET /health` | Liveness + configured provider (never secrets). |

## 7. UI/UX requirements

- First screen answers "what do I do?": an upload area with plain-language
  text, then the library.
- Persistent banner: "ClaimTrace helps you read documents. It is not legal
  advice. Always check the quoted source."
- Every extracted item shows its quote and location one click away; quotes are
  shown verbatim, never paraphrased.
- Status labels use words and colour together (never colour alone).
- Low-confidence or unverified items carry a visible "Needs review" badge.
- Views: Library · Document (Commitments / Claims / Definitions / Graph) ·
  Deadlines · Ask · Verify · Review queue · Report.
- Keyboard reachable, semantic HTML, WCAG 2.2 AA contrast, ARIA live region for
  processing status.
- No jargon in UI copy: "Who must do it", "For whom", "By when", "Unless".

## 8. Evaluation plan (detail in `docs/evaluation.md`)

- Synthetic, clearly fictional documents (no real contracts) with labelled
  ground truth in `evals/`.
- Suites: extraction, deadlines/conditions, consistency, contradiction,
  grounded QA, evidence gap, amendment/supersession, ambiguity.
- Metrics: commitment P/R/F1 (span-overlap matching), party attribution
  accuracy, deadline accuracy, answer-status accuracy, citation precision/recall,
  verification verdict accuracy, contradiction P/R, hallucination rate
  (quotes not found verbatim + answers asserted when gold is not_addressed),
  not-found accuracy, calibration (accuracy per confidence bucket),
  latency, cost (tokens), review burden (% flagged).
- Runner: `claimtrace eval run --suite core --model rules|openai:<m>|ollama:<m>`
  writes `evals/runs/<timestamp>/` with raw outputs, versions, per-case results.
- Honesty rule: the README reports the latest committed baseline, including
  where it is bad. The benchmark author also wrote the baseline; this bias is
  stated in the README until external cases are added.

## 9. Security and privacy requirements

- Local-first: no network egress unless the user configures an external LLM
  provider or enables URL ingestion. Both are off by default and visible in
  `/health`.
- Uploads: size cap (default 20 MB), extension + magic-byte allowlist, PDF
  page cap, DOCX zip-bomb guard (uncompressed size cap), no execution of
  embedded content. Files are parsed, never rendered server-side.
- URL ingestion: http/https only, DNS resolve and block private, loopback,
  link-local, multicast and reserved ranges, no redirects to blocked ranges,
  response size and time caps.
- Prompt injection: document text is wrapped as data, the model is told it is
  untrusted, model output must validate against a schema, every quote must be
  found verbatim in the cited passage or the item is dropped/flagged. Model
  output can never trigger an action (there are no actions to trigger).
- Logs: structured JSON with IDs, counts and durations only; never document
  text, questions, or API keys.
- Deletion: `DELETE /documents/{id}` removes the file, passages, extracted
  objects, edges, answers citing it, and findings. Optional retention period
  (`CLAIMTRACE_RETENTION_DAYS`) purges old documents on startup.
- Secrets only via environment variables; `.env` is git-ignored.

## 10. Technical architecture (detail in `docs/architecture.md`)

```
apps/web (React + Vite + TS) ──HTTP──> apps/api (FastAPI)
                                          │
        ┌────────────────┬────────────────┼──────────────┬───────────────┐
   ingestion        extraction        retrieval     verification     evaluation
 (pdf/docx/md/txt  (rules, LLM;     (BM25 over     (ask, verify,    (datasets,
  /url, passages)   quote check)     passages+      findings)        metrics, runner)
                                     commitments)
        └────────────────┴──────── core (models, graph, store) ──────────────┘
                                          │
                               integrations (LLM providers)
                                          │
                                   SQLite (one file)
```

Decisions:

- **One Python distribution (`claimtrace`) with subpackages** matching the
  required `packages/*` layout, rather than seven separately versioned
  packages. Reversible: each subpackage only imports `core` and its own
  dependencies.
- **Seams only where two adapters exist.** LLM provider: `rules` (none),
  `openai` (OpenAI-compatible, also covers Ollama, vLLM, LM Studio), `fake`
  (tests). Store: SQLite only in v0.1, behind a `Store` class whose interface is
  written so a Postgres adapter is mechanical later.
- **Rules baseline first.** The deterministic extractor gives a floor, works
  offline, and makes the eval meaningful when someone plugs in a model.
- **Quotes are verified by string match against stored passages.** This is the
  core trust mechanism; it applies equally to rules and LLM output.

## 11. Release plan

| Version | Theme | Must contain |
|---|---|---|
| v0.1 | Trustworthy single-user slice | §3 scope, eval baseline, Docker Compose, docs |
| v0.2 | Better reading | OCR (Tesseract), table extraction, embeddings + hybrid retrieval, LLM extraction tuned on eval, deadline calendar export (ICS, user-initiated) |
| v1.0 | Team use | Auth + roles, Postgres adapter, audit log, multi-document evidence mapping at scale, external benchmark cases, plugin API for extractors |

## 12. Risks, mitigations, open questions

| Risk | Mitigation |
|---|---|
| Users treat output as legal advice | Banner, report footer, docs; no "risk scores". |
| Rules extractor misses obligations phrased unusually | Publish recall honestly; LLM extractor optional; review queue. |
| LLM hallucinated quotes | Verbatim quote check; drop or flag. |
| Self-written benchmark overstates quality | Disclose; invite external cases; keep held-out set. |
| Party resolution errors ("the Supplier" vs "Acme") | Definitions-driven alias table; ambiguous → needs review. |
| Malicious files | Type/size/page caps, no rendering, parser hardening, fuzz tests. |

Open questions: (1) default LLM for the "recommended" setup; (2) whether
"fulfilled" status should only ever be set by a human; (3) license of any
public datasets used for future external eval (CUAD is CC BY 4.0).
