# ClaimTrace data model

Describes commit 1899c3c.

Source files: `packages/core/models.py`, `packages/core/store.py`,
`packages/core/migrations/001_init.sql`, `packages/core/text.py`. Where the code differs from
`docs/product-spec.md` or `docs/design-review.md`, the difference is noted.

## 1. Enums

| Enum | Values | Notes |
|---|---|---|
| `DocType` | contract, amendment, sow, proposal, policy, audit_report, evidence, report, other | `EVIDENCE_TYPES` = {audit_report, evidence, report}. |
| `CommitmentType` | obligation, entitlement, prohibition, condition, deadline, consequence, service_level | The rules extractor never emits `deadline`; only the LLM extractor can. |
| `Modality` | must, must_not, may, reasonable_efforts | |
| `DocumentEffect` | in_force, replaced, deleted | D2 lists in_force, amended, replaced, deleted, superseded. The code has three values; "amended" and "superseded" exist only in `CommitmentStatus`. |
| `Lifecycle` | open, fulfilled, disputed, unknown | Set only through a review request (D2). Default `unknown`. |
| `CommitmentStatus` | stated, amended, superseded, open, fulfilled, disputed, unknown | Derived; see section 2.4. `unknown` is never returned by `derive_status`. |
| `Confidence` | high, medium, low, unknown | Ordered unknown < low < medium < high. `cap_confidence(c, ceiling)` lowers to the ceiling, never raises. |
| `AnswerStatus` | stated, implied, contradicted, not_addressed, ambiguous, needs_human_review | |
| `Verdict` | consistent, contradicted, partially_supported, not_addressed, ambiguous, needs_human_review | No code path produces `ambiguous`. |
| `Severity` | high, medium, low, info | |
| `EdgeType` | made_by, owed_to, requires, conditioned_on, amends, supersedes, supports, contradicts, qualifies, depends_on, duplicates, references, evidence_for | See section 6. |
| `ReviewDecisionKind` | accept, reject, request_evidence, note, resolve | |
| `ReviewStatus` | unreviewed, accepted, rejected, needs_evidence, resolved | `DECISION_TO_STATUS` maps accept→accepted, reject→rejected, request_evidence→needs_evidence, resolve→resolved. `note` changes nothing. |

All models forbid extra fields (`extra="forbid"`).

## 2. Models

### 2.1 Provenance and spans

| `Span` field | Meaning |
|---|---|
| document_id, passage_id | Where the quote is. |
| char_start, char_end | Offsets into the document's stored normalised text (not the passage). |
| quote | `text[char_start:char_end]` at creation time. |
| page, section | Copied from the passage (page is `None` for Markdown and DOCX). |
| document_title, document_version | Copied for display. |
| locator | v0.2: copied from the passage, e.g. `table 1, row 3` for a DOCX table row. |

| `Provenance` field | Meaning |
|---|---|
| source_document_id, document_version | Origin document. |
| span | The exact text the object was extracted from. |
| extraction_method | `rules`, `llm`, or `rules+llm` (rules item the model independently found with the same party). |
| extractor_version | `EXTRACTOR_VERSION` (`rules-0.2.0`), also on LLM items. |
| model, endpoint_host, prompt_version | Set for LLM items (`extract-commitments-v1`). |
| extracted_at | UTC time. |
| confidence | Copy of the object's confidence at creation. |
| review_status | Default `unreviewed`; the commitments endpoint fills it from the review table on read. |

### 2.2 Documents and passages

| `Document` field | Meaning |
|---|---|
| id | `doc_` + 12 hex. |
| title, version_label, doc_type, author, filename | From upload form, Markdown front matter or file metadata. `doc_type` falls back to filename keywords (amend, audit, policy, sow, proposal, record, evidence, report, agreement, contract, msa). |
| source | `upload` or `url`. |
| uploaded_at | UTC; retention purge uses it. |
| checksum_sha256 | SHA-256 of the uploaded bytes. Uploading identical bytes returns the existing document. |
| text_sha256 | SHA-256 of the stored normalised text. |
| normalizer_version | `NORMALIZER_VERSION` at ingest (`norm-1`). |
| page_count | PDF only. |
| status | parsed, analyzing, analyzed, failed (a plain string). |
| warnings | Strings; `SCANNED:`, `INJECTION:`, `HIDDEN:` (v0.2) and `OCR:` (v0.2) prefixes mark the loud warnings. |
| tags | Free strings; sample documents get `sample`. |
| amends_document_id | The document this one amends. The spec's `related_to`/`relation` fields do not exist. |
| allow_external_llm | Per-document opt-in for non-loopback LLM endpoints (D14). |

`Passage`: id (`psg_<doc hex>_<ordinal:04d>`), document_id, ordinal, page, section_number,
section_title, char_start, char_end, text, and (v0.2, optional) `hidden_text` (why part of it is
invisible to a reader), `ocr_confidence` (page mean OCR word confidence, 0–100) and `locator`
(`table N, row M`). Section numbers inside a schedule look like `Schedule 2/1.1`.

### 2.3 Extracted objects

| Model | Fields |
|---|---|
| `Party` | id (`pty_`), document_id, name, alias, provenance. Created from `Name (the "Alias")` when the name has a company suffix or the alias is a role word. |
| `Definition` | id (`def_`), document_id, term, definition_text, provenance. From `"Term" means ...`. |
| `Commitment` | See `docs/commitment-model.md`. id is `cmt_` + 12 hex; commitments derived by a "modify" amendment use `cmt_d_` + 12 hex. |
| `Deadline` | kind (absolute, relative, recurring, vague, none), raw, date, offset_days, business_days, anchor, ambiguous_format. A `none` deadline is stored as `deadline: null`. |
| `Claim` | id (`clm_`), document_id, text, claim_type (scope_limit, control, measurement, event, statement), section_number, confidence (always high), needs_review (always false), provenance. Extracted only from audit_report, evidence and report documents. |
| `AmendmentInstruction` | id (`ins_`), document_id, target_section, action (replace, delete, insert, modify), new_text, provenance (span of the whole instruction). |
| `Edge` | id, src_id, dst_id, type, document_id (nullable), provenance (nullable), created_at. |

### 2.4 Derived status (D2)

`derive_status(c)` in order:

1. document_effect replaced or deleted → `superseded`
2. lifecycle fulfilled → `fulfilled`
3. lifecycle disputed → `disputed`
4. `amends_section` set (the commitment is replacement text from an amendment) → `amended`
5. lifecycle open → `open`
6. otherwise → `stated`

It is recomputed after extraction, after amendment application, and when a reviewer sets
`lifecycle`.

### 2.5 Answers, verification, reviews, runs

| Model | Fields |
|---|---|
| `Citation` | span, role (supports, conflicts, checked_not_supporting, context), verified, note. |
| `GraphStep` | node (label), edge (edge to the next step or `None`). |
| `Answer` | id (`ans_`), question, document_ids (scope), status, answer_text, confidence, citations, graph_path, caveats, follow_ups, review_status, needs_review, run_manifest, created_at. |
| `Finding` | id (`fnd_`), run_id, verdict, subject_id, subject_text, subject_span, supporting, conflicting, explanation, severity, recommended_action, sufficiency (`reviewer_judgement_required` or `None`), review_status. |
| `VerificationRun` | id (`ver_`), base_document_id, other_document_id, mode (amendment, evidence, version, general), findings, summary (count per verdict), run_manifest, created_at. |
| `ReviewDecision` | id (`rev_`), target_kind (commitment, answer, finding), target_id, decision, note, reviewer, reviewer_verified (always false: no accounts), prior_status, target_hash (SHA-256 of the target's JSON at review time), at. |
| `AnalysisRun` | id (`run_`), document_id, extractor_version, status (queued, running, done, failed), error, counts, run_manifest, created_at, finished_at. |

Run manifests (D8):

| Where | Keys |
|---|---|
| AnalysisRun | claimtrace_version, document_checksum, text_sha256, normalizer_version, extractor_version, model, provider, endpoint_host, prompt_version |
| Answer | claimtrace_version, composer (`rules` or `llm`), documents {id: {checksum, version}}; with the LLM composer also llm, model, endpoint_host, prompt_version (`answer-v1`) |
| VerificationRun | claimtrace_version, extractor_version, method (`rules`), documents {id: {title, version, checksum, text_sha256}} |

No manifest records a parser version, which D8 lists.

## 3. SQLite tables

Objects are stored as validated JSON plus a few indexed columns. Reads re-validate the JSON,
so a corrupt row raises. Connection settings: `foreign_keys=ON`, WAL (file databases),
`busy_timeout=5000`, one connection shared across threads behind an `RLock`. Migrations are
numbered files in `core/migrations/`; `schema_version` records the applied numbers. Only
`001_init.sql` exists.

| Table | Columns | Foreign keys |
|---|---|---|
| documents | id PK, checksum, title, text (normalised text), json, created_at | |
| passages | id PK, document_id, ordinal, json | documents ON DELETE CASCADE |
| objects | id PK, kind (commitment, claim, party, definition, amendment_instruction), document_id, section_number, json | documents ON DELETE CASCADE |
| edges | id PK, src_id, dst_id, type, document_id (nullable), json | documents ON DELETE CASCADE |
| analysis_runs | id PK, document_id, idem_key, json | documents ON DELETE CASCADE |
| answers | id PK, json, created_at | |
| answer_documents | answer_id, document_id (PK both) | answers and documents ON DELETE CASCADE |
| verification_runs | id PK, base_document_id, other_document_id, json, created_at | both documents ON DELETE CASCADE |
| findings | id PK, run_id, json | verification_runs ON DELETE CASCADE |
| reviews | id PK, target_kind, target_id, json, at | none |
| tombstones | document_id PK, checksum, deleted_at, reason, counts (JSON) | none |
| egress_log | id autoincrement, document_id, host, bytes, purpose, at | none |
| schema_version | version | none |

Findings are stored twice: inside `verification_runs.json` and as rows in `findings`.
`get_verification` replaces the embedded findings with the rows, so a finding's stored row
is the source of truth.

`answer_documents` links an answer to every document in its scope and every document it
cites.

## 4. Deleting a document (D15)

`Store.delete_document(doc_id, reason)` runs in one transaction:

| Removed | How |
|---|---|
| Review rows targeting the document's objects, the answers linked to it, and the findings of verification runs that involve it | Explicit `DELETE FROM reviews` |
| Edges whose src or dst is one of its objects, or the document id itself | Explicit delete (catches `supersedes` and `amends` edges, which have `document_id` NULL) |
| Answers linked through `answer_documents` | Explicit delete (whole answer, even if it also cites other documents) |
| The documents row | Explicit delete |
| Passages, objects, edges with this `document_id`, analysis runs, verification runs where it is base or other, their findings, answer_documents rows | `ON DELETE CASCADE` |

It then inserts a tombstone (document_id, checksum, deleted_at, reason, counts of objects,
answers, verification_runs and reviews removed) and runs `compact()`: WAL checkpoint
(TRUNCATE), `VACUUM`, checkpoint again. The API and retention purge then call
`apply_amendments`, which resets amendment effects on documents that are left (deleting an
amendment restores the base commitments to `in_force`).

Tombstones hold no text. `reason` is `user_request` or `retention_<N>d`. Retention purge
(`CLAIMTRACE_RETENTION_DAYS`) runs in a daemon thread at startup and then hourly, deleting
documents whose `uploaded_at` is older than the limit. `GET /privacy/tombstones` lists them.

## 5. Append-only reviews and the egress log

The `reviews` table has a trigger:

```sql
CREATE TRIGGER reviews_no_update BEFORE UPDATE ON reviews
BEGIN SELECT RAISE(ABORT, 'reviews are append-only'); END;
```

It blocks `UPDATE` only. `DELETE` is allowed and is used by document deletion, so the
review trail of a deleted document is removed (D15 takes precedence over D7 here). Current
review status is derived: the latest non-`note` decision for the target, ordered by `at` then
rowid (`Store.current_review_status`). Setting `lifecycle` on a commitment review updates the
commitment row; the review row records `prior_status` and `target_hash` from before the
change.

`egress_log` records every call to an LLM endpoint: document_id, host, request bytes,
purpose (`extract` per batch of passages, `answer` once per document whose passages were
sent), and time. No content. Calls to loopback endpoints are logged too, because the
provider has a host. `GET /privacy/egress` returns the log. Egress rows are not removed when
a document is deleted.

## 6. Graph: node and edge types

`GET /documents/{id}/graph` returns nodes and edges for one document. Node types:

| Node type | Source |
|---|---|
| document | The document itself. |
| party | `Party` objects. |
| commitment | `Commitment` objects of this document (not those of its amendments). |
| claim | `Claim` objects. |
| deadline, condition | Synthetic edge endpoints `deadline:<date or raw>` and `condition:<text[:80]>`. |
| external | Any other edge endpoint not in the list, such as an amending document's id or a commitment in another document. |

Definitions and amendment instructions are not graph nodes.

Edges at this commit:

| EdgeType | Emitted? | Created by | src → dst | document_id |
|---|---|---|---|---|
| made_by | yes | `extract_rules` | commitment → party (obliging party is a defined party) | extracting doc |
| owed_to | yes | `extract_rules` | commitment → party (beneficiary) | extracting doc |
| requires | yes | `extract_rules` | commitment → `deadline:…` (any deadline kind except none) | extracting doc |
| conditioned_on | yes | `extract_rules` | commitment → `condition:…` per condition | extracting doc |
| references | yes | `extract_rules` | commitment → commitment in the same document with a referenced section number | extracting doc |
| qualifies | yes | `extract_rules` | condition commitment → commitments in its first referenced section | extracting doc |
| amends | yes | `apply_amendments` | amendment document → base document | NULL |
| supersedes | yes | `apply_amendments` | replacement commitment → replaced or deleted commitment | NULL |
| supports | no | defined only | | |
| contradicts | no | defined only | | |
| evidence_for | no | defined only | | |
| depends_on | no | defined only | | |
| duplicates | no | defined only | | |

Verification and answers do not write edges; their links between documents live in
`Finding` and `Citation` spans. Commitments added by the LLM extractor get no edges.
`apply_amendments` deletes and rebuilds all `amends` and `supersedes` edges on every run.
`references` and `qualifies` edges do not cross documents.

`Answer.graph_path` is a readable path built in `ask._graph_path`: party → commitment →
deadline, then "superseded by", "Replaced by" or nothing. It is a list of labels, not edge
ids.

## 7. Offsets and normalisation invariants (D9)

`core.text.normalize` (version `norm-1`): NFKC; non-breaking and thin spaces to space;
soft hyphen, zero-width space and BOM removed; curly quotes to straight; en and em dash to
`-`; CRLF/CR to LF; tab to space; `word-\nword` joined; text split on blank lines, each
paragraph's runs of spaces and newlines collapsed to one space, empty paragraphs dropped,
paragraphs joined with `\n\n`. Bump `NORMALIZER_VERSION` whenever output changes.

Invariants:

1. `segment()` normalises each parser block separately and joins them with `\n\n`. The
   joined string is stored once in `documents.text`; `text_sha256` is its hash.
2. For every passage, `text[p.char_start:p.char_end] == p.text`.
3. Every span's `char_start`/`char_end` are document offsets: passage start plus the
   offset within the passage. `quote == text[char_start:char_end]` when created.
4. Passages are written once at ingest. Analysis never changes the stored text or passage
   offsets; it only replaces objects and edges.
5. Rules commitments assert at creation that their quote is found in the passage.
   LLM quotes are located with `find_quote` (exact, or case- and whitespace-insensitive);
   model offsets are never used.
6. Answer citations are re-checked before saving (`verify_citation`: exact at the offsets,
   or `find_quote` anywhere in the stored text). Reports re-check exact offsets only and
   list mismatches under `integrity_failures`.

Known gap: there is no re-ingest path for a normaliser change. Uploading the same bytes
returns the existing document by checksum, so a document must be deleted and uploaded again
to get text from a newer normaliser.
