# ClaimTrace — Design Review (Phase 2)

Date: 2026-11-18 · Input: `docs/product-spec.md` (draft of 2026-11-18)
Method: 11 reviewers, each run as an isolated agent with no access to the
others' output or to the authoring conversation. Full reviews are in
[`docs/reviews/`](reviews/). This document is the chair's synthesis. Where the
synthesis departs from the original brief, the departure is listed in §6.

## 1. Panel summary

| # | Reviewer | Sharpest concern | Key recommendation adopted |
|---|---|---|---|
| 1 | [Product strategist](reviews/01-product-strategist.md) | No wedge. "Why not ChatGPT with the PDF?" has no answer. | Lead with **amendment drift** (contract + amendments → what governs now). |
| 2 | [Contract domain](reviews/02-contract-domain.md) | Status enum mixes document effect with lifecycle. The model cannot express procure-that obligations, passive voice, or relative deadlines. | Split status. Add `performer`, `modality`, relative deadlines with an anchor. |
| 3 | [Audit & compliance](reviews/03-audit-compliance.md) | "Consistent" on audit evidence reads as an opinion. Deleting a document erases the review trail. | Evidence located ≠ sufficient. Review events are append-only. Run manifests. |
| 4 | [ML researcher](reviews/04-ml-researcher.md) | The same team writes the benchmark and the rules, so scores are inflated. Matching criteria are undefined. | Fix the metric definitions before coding. Add bootstrap CIs and a trivial keyword baseline. |
| 5 | [Backend](reviews/05-backend-engineer.md) | Analyze is unspecified as sync or async. Offsets break when the normaliser changes. Delete cascade is undefined. | Async run entity. Store the normalised text once, with a hash. FK cascades. Migrations. |
| 6 | [Frontend/UX](reviews/06-frontend-ux.md) | 7+ views. Review as a destination. Graph view costs more than it is worth. | 4 destinations. A shared EvidenceQuote component. Graph shown as a breadcrumb. |
| 7 | [Security](reviews/07-security-engineer.md) | SSRF check-then-fetch. XXE/zip bombs. No bind address or CORS policy. | Pinned-IP fetch. defusedxml. Subprocess parse with rlimits. 127.0.0.1 bind. Origin checks. |
| 8 | [Privacy](reviews/08-privacy-governance.md) | An on/off provider switch is not consent. Erasure misses notes, WAL and eval runs. | Per-document external-LLM opt-in. Canary-string erasure test. No telemetry. |
| 9 | [OSS maintainer](reviews/09-oss-maintainer.md) | No licence. AGPL temptation (PyMuPDF). Bus factor of 1. | Apache-2.0. A CI licence gate. One distribution, one version. |
| 10 | [Red team](reviews/10-red-team.md) | A verbatim quote can still be wrong in context. Hidden text gets into passages. | Two-stage quote check: verbatim, plus a scan of the clause and its neighbours for qualifiers. |
| 11 | [End-user advocate](reviews/11-end-user-advocate.md) | Docker is a barrier. "High confidence" will be over-trusted. Enum jargon. | Plain-language labels. A "documents you have not uploaded" notice. Loud scanned-PDF warning. |

Points of agreement across reviewers (≥3 raised independently):

- **Defer the interactive graph** (1, 6, 11). Show provenance as a readable
  path instead.
- **Two quote checks are not enough on their own; context matters** (4, 7, 10).
- **Delete/retention must be tested, not asserted** (3, 5, 8).
- **URL ingestion is high-risk surface for low v0.1 value** (1, 7, 9).
- **The rules baseline will under-deliver on real contracts, so be honest
  about it** (1, 2, 4, 9).

Real disagreements and how they were resolved:

- *Default extractor.* The strategist wants the LLM path to be the default. The
  end-user advocate and the privacy reviewer want offline-by-default with no
  first-run model choice. **Decision:** offline rules is the default and needs no
  setup. One environment variable enables a model. External (non-loopback)
  providers also need per-document opt-in. The README states plainly that
  recall is limited without a model.
- *Delete vs audit trail.* The privacy reviewer wants complete erasure; the audit
  reviewer wants the trail kept. **Decision:** delete removes all content (text,
  quotes, notes) and leaves a content-free tombstone (IDs, checksums,
  timestamps). Exported reports are outside the system and stay verifiable
  against the checksums they embed.
- *URL ingestion.* The brief requires it; reviewers 1 and 9 say cut it.
  **Decision:** implement it disabled by default, with a pinned-IP fetch,
  per-hop revalidation and size/time caps, and test it adversarially. If those
  tests cannot be made to pass, it ships off and is marked experimental.

## 2. Final MVP decision record

| ID | Decision | Rationale | Reversible? |
|---|---|---|---|
| D1 | The v0.1 demo and messaging lead with **amendment drift**: contract + amendment(s) → register showing what governs now, with original and amended text side by side. Other journeys work but are secondary. | It is the one job a chat tool does not do reliably; it needs persistent multi-document state and a review trail. | Yes, messaging only. |
| D2 | Commitment status splits into `document_effect` (in_force, amended, replaced, deleted, superseded) and `lifecycle` (open, fulfilled, disputed, unknown). Lifecycle is **set only by a human**. The brief's single `status` is still exposed as a derived field for compatibility. | Contract reviewer: the two axes conflate. Answers open question 2. | Yes. |
| D3 | Commitment adds `performer_party`, `modality` (must / must_not / may / reasonable_efforts), `deadline.kind` (absolute, relative, recurring, vague) with `anchor` + `offset`, and `exceptions` / `subject_to`. A date is computed only when the anchor is resolved. | Contract reviewer. Never guess dates. | Yes, additive. |
| D4 | **Two-stage grounding check.** (1) The quote must occur verbatim, after whitespace/quote normalisation, in the cited passage. (2) A qualifier scan of that sentence and the next sentence for *except, unless, subject to, notwithstanding, provided that, save that, not*. A hit adds a caveat and caps confidence at medium. | Red team: a verbatim quote can be wrong in context. | Yes. |
| D5 | Confidence stays categorical and rule-derived (high/medium/low/unknown, rules in `docs/commitment-model.md`). The UI shows plain wording ("Found in text — check §2.1") and every answer carries "Only covers the documents you uploaded". | End-user advocate: prevents over-trust. | Yes. |
| D6 | Evidence checks (contract vs audit/evidence) never return a bare "consistent". The result is `evidence_located` plus `sufficiency: reviewer_judgement_required`; the UI says "Evidence found — you decide if it is enough". The verdict enum is unchanged; `consistent` in this mode means *the located text agrees with the stated term* and nothing more. | Audit reviewer. | Yes. |
| D7 | Review decisions are **append-only** rows (reviewer name, self-declared flag, UTC time, prior state, target content hash). Current state is derived from the latest row. | Audit trail. | Yes. |
| D8 | Each analysis/ask/verify stores a **run manifest**: document checksums, normalised-text hash, parser, normaliser, extractor and prompt versions, model, endpoint host, config. Exports embed it. | Reproducibility. | Yes. |
| D9 | Normalised text is stored once per document with `text_sha256` and `normalizer_version`. Spans index into it. Re-analysis never mutates offsets; a parser change means a new document version. | Offset stability. | Yes. |
| D10 | `POST /documents/{id}/analyze` returns **202 + AnalysisRun**. It runs in-process in a background thread. A unique key on (document, text hash, extractor version) gives idempotency. | Backend. | Yes. |
| D11 | SQLite with `foreign_keys=ON`, WAL, `ON DELETE CASCADE`, numbered migrations from day one. A `Store` class is the single persistence seam. No Postgres adapter in v0.1. | Backend, maintainer. | Yes (seam exists). |
| D12 | Parsing runs in a **subprocess with CPU, memory and time limits**. DOCX: defusedxml, per-member compression-ratio cap, reject macros/OLE/external relationships. PDF: reject encrypted files, `/JavaScript`, `/Launch` and `/EmbeddedFile`; detect scanned (no text layer) and say so loudly. | Security. | Yes. |
| D13 | Server binds **127.0.0.1** by default. CORS allows the UI origin only. Unsafe methods require a same-origin `Origin`. An optional bearer token (`CLAIMTRACE_API_TOKEN`) is required whenever the bind is non-loopback. | Security. Localhost drive-by attacks. | Yes. |
| D14 | External LLM providers (any non-loopback endpoint) need a global setting **and** a per-document `allow_external_llm` flag. Each send is logged locally (host, doc ID, byte count). A local Ollama endpoint needs only the global setting. | Privacy. | Yes. |
| D15 | Delete removes all content and derived rows, then runs WAL checkpoint and VACUUM, leaving a content-free tombstone. A canary-string test greps the database file afterwards. Retention purge runs on a timer and at startup, keyed to upload time. | Privacy + audit. | Yes. |
| D16 | No telemetry, no update checks, no CDN assets. Tests fail on any outbound socket in the default suite. | Privacy. | Yes. |
| D17 | UI: **4 destinations** (Library, Document, Ask, Verify). Review is a filter and a count badge, not a page. Report and CSV are actions. Graph shown as an accessible path ("MSA §2.1 → replaced by Amendment 1 §1.1") plus a related-items table. The interactive force graph is deferred. | UX, end-user advocate, strategist. | Yes. |
| D18 | Plain-language labels in the UI; API enums stay precise. Mapping: stated → "Stated", contradicted → "Conflicts", not_addressed → "Not mentioned", ambiguous → "Unclear — please read", needs_human_review → "Needs your review", partially_supported → "Partly supported". | End-user advocate. | Yes. |
| D19 | React + Vite SPA built to static files and served by FastAPI. One process, one container, no Node at runtime. | UX, backend. | Yes. |
| D20 | Two install paths: `pip install -e . && claimtrace serve` (no Docker) and `docker compose up`. A desktop bundle is deferred. | End-user advocate. | Yes. |
| D21 | Apache-2.0. Parsers: pypdf (BSD), python-docx (MIT), defusedxml (PSF). A CI licence gate fails on GPL/AGPL. | Maintainer. | Yes. |
| D22 | Eval metric definitions are fixed in `docs/evaluation.md` before the extractor is tuned. Report bootstrap 95% CIs and per-suite n. Include a trivial keyword baseline. At least 25% of QA cases have not-found gold. No "A beats B" claim inside the CIs. | ML researcher. | Yes. |
| D23 | Bundled sample documents (CC0, fictional) and a "Load sample documents" button, so the first run shows value with zero uploads. | Maintainer, end-user advocate. | Yes. |
| D24 | Verify is a pipeline: pair candidates by clause number, party, type and lexical overlap, then compare normalised fields (date, amount, duration, percentage, modality, polarity). Weak pairings become `needs_human_review`, never `consistent`. | ML researcher. A false clear is worse than a false alarm. | Yes. |

## 3. Prioritised backlog

**P0 — v0.1 blockers**

1. Core models (D2, D3) + Store with migrations, FK cascades (D11).
2. Ingestion: MD/TXT/DOCX/PDF in a sandboxed subprocess (D12), passages with
   page/section/offsets, normalised text hash (D9), scanned-PDF detection.
3. Rules extractor: modal-verb inventory (shall, must, will, agrees to,
   undertakes, is responsible for, shall not, may, is entitled to), lead-in
   lists, defined-term parties, deadlines (absolute + relative), exceptions.
4. Amendment application: "Clause X is deleted and replaced with …",
   "added as clause X", "deleted" → `replaced`/`deleted` + `amends`/`supersedes`
   edges; original and new text both kept (D1).
5. Two-stage grounding check (D4); confidence rules (D5).
6. `/ask`: BM25 over passages + commitments, deterministic answer composer,
   not-found path, optional LLM composer with schema validation + quote check.
7. `/verify`: pairing + typed comparison (D24), evidence mode (D6).
8. Append-only reviews (D7), run manifests (D8), reports md/json/html + CSV.
9. Security baseline (D12, D13), delete + canary test (D15), no-egress
   test (D16), log redaction test.
10. Web UI (D17–D19) with EvidenceQuote component and sample-docs button.
11. Eval: 120 cases, runner, metrics with CIs, keyword baseline (D22).
12. Docs, licence, CI, Docker Compose.

**P1 — v0.1 if time allows, otherwise v0.2**

13. URL ingestion with SSRF protections (ships disabled).
14. OpenAI-compatible extractor with per-document egress gate (D14).
15. Retention timer.
16. Cross-reference resolver ("subject to clause 9") → `references` edges.

**P2 — v0.2+**

OCR; hidden-text detection (white text, tiny fonts, DOCX hidden runs);
embeddings + hybrid retrieval (after retrieval recall@k is logged); business-day
calendars; order-of-precedence logic; ICS export; interactive graph; external
held-out benchmark (CUAD-derived); desktop bundle; Postgres adapter; RBAC.

## 4. Rejected ideas and rationale

| Idea | Why rejected (for now) |
|---|---|
| Numeric confidence scores / ECE | No calibrated probability exists; n≈120 makes ECE noise. Categorical + per-bucket accuracy instead. |
| Fine-tuned NLI model for contradiction | Data too small; typed field comparison plus an optional LLM is more auditable. |
| Seven separately versioned Python packages | Release matrix no one maintains. One distribution, subpackages in the brief's layout, import direction tested. |
| Next.js | Adds a Node server for a single-user, self-hosted tool. Vite SPA meets the "React" requirement. |
| Interactive force-directed graph in v0.1 | Inaccessible, unreadable past ~50 nodes, no persona job depends on it. |
| Separate "Review queue" page | Review is a state of items; a filter avoids drift between views. |
| Auto-redaction of PII before LLM calls | Unreliable; gives false assurance. Per-document opt-in gate first. |
| Clause "risk scores" | Reads as legal advice. |
| PyMuPDF | AGPL-3.0 conflicts with Apache-2.0 distribution. |
| SQLCipher / field encryption | No key management story in single-user v0.1; document disk encryption instead. |

## 5. Risk register

Severity / likelihood: H/M/L. Owner = role accountable.

| # | Risk | Sev | Lik | Mitigation | Owner |
|---|---|---|---|---|---|
| R1 | User treats output as legal advice or a clearance | H | M | Banner, report footer, "what we did not check" section, no risk scores | Product |
| R2 | False "consistent" (missed change) | H | M | D24: weak pairing → needs review; unmatched commitments listed as not_addressed | ML |
| R3 | Verbatim-but-misleading quote | H | M | D4 qualifier scan; red-team eval cases | ML |
| R4 | Rules recall poor on real contracts; bad first impression | H | H | Honest README numbers; LLM path; review queue; sample docs | Product |
| R5 | Benchmark self-authored → inflated scores | M | H | Disclosure, keyword baseline, CIs, external set as v0.2 blocker for comparative claims | ML |
| R6 | Malicious file DoS / XXE | H | M | D12 sandbox + defusedxml + caps; fuzz-style tests | Security |
| R7 | Localhost API abused by a web page (CSRF / DNS rebinding) | H | L | D13 Origin + Host checks, CORS allowlist, loopback bind | Security |
| R8 | Documents sent to a third-party LLM without informed consent | H | M | D14 per-document opt-in + send log | Privacy |
| R9 | Incomplete erasure | M | M | D15 canary test after VACUUM | Privacy |
| R10 | Superseded term shown as current | H | M | D2/D1 document_effect + amendment caveat on answers | Domain |
| R11 | Offsets drift after upgrade, breaking citations | M | M | D9 stored text + hash; report re-verification | Backend |
| R12 | SSRF via URL ingestion | H | L | Off by default; pinned IP; per-hop checks | Security |
| R13 | Review fatigue (>30% flagged) | M | M | Measure review burden in eval; tune flags | UX |
| R14 | Maintainer bus factor 1 | M | H | Docs, good first issues, small surface | Maintainer |
| R15 | Hidden text in PDFs/DOCX injects commitments | M | L | v0.2 detection; v0.1 documents it as a known limitation | Security |

## 6. Departures from the original brief

These are deliberate and reversible; each is recorded so the brief's author
can overrule them.

1. **Next.js → Vite + React SPA** (D19).
2. **"Claim graph visualization" → accessible path + related-items table**;
   interactive graph is v0.2 (D17). The graph API (`GET /documents/{id}/graph`)
   is complete.
3. **Single `status` → `document_effect` + `lifecycle`**; `status` remains as a
   derived field mapping to the brief's enum (D2).
4. **Postgres / graph-DB / vector-store adapters**: not built; `Store` and
   `LLMProvider` are the seams (D11). Building an adapter with no second
   implementation would be speculative.
5. **Claims extraction** is limited to factual assertions in audit/evidence
   documents ("X is encrypted", "availability was 99.1%"); contracts mainly
   yield commitments.
6. **Benchmark** is 120 cases as required, but clause-level cases dominate,
   and comparative claims wait for an external held-out set (D22, R5).

## 7. Definition of done for v0.1

A release candidate is done when every item is true and checked in CI or by a
recorded manual check:

- [ ] Fresh clone → `make dev` / `pip install -e .` → `claimtrace serve` →
      "Load sample documents" → register visible in < 5 minutes, offline, no key.
- [ ] `docker compose up` serves the same app on 127.0.0.1 with a healthcheck.
- [ ] MSA + Amendment 1 sample: register shows 2.1/3.2/5.3 as *replaced* with
      both texts; `/ask "Did the vendor promise delivery by March 31?"` answers
      with the quote, the replacement caveat and both locations.
- [ ] `/ask` for an absent topic returns exactly "I could not find support for
      this in the uploaded documents."
- [ ] `/verify` MSA vs audit report flags data location (UK vs Dublin) as
      contradicted and MFA as partially supported, with evidence-sufficiency
      wording.
- [ ] Every returned quote passes the verbatim check (tested property).
- [ ] Eval suite of ≥120 cases runs via `claimtrace eval run --suite core
      --model rules`; report has per-suite n and 95% CIs; README shows the
      numbers and limitations.
- [ ] Tests: unit + API integration + one browser end-to-end; lint (ruff),
      types (mypy on core), web typecheck; all green in CI.
- [ ] Security tests: XXE/billion-laughs DOCX, zip-ratio bomb, PDF with
      JavaScript, XSS strings in documents, foreign-Origin DELETE, SSRF to
      private/metadata IPs, log redaction.
- [ ] Privacy tests: delete + canary grep, no outbound sockets, per-document
      LLM gate.
- [ ] Accessibility: keyboard-only walkthrough recorded; axe check with no
      serious violations on the four destinations.
- [ ] Docs listed in Phase 7 exist; LICENSE Apache-2.0; licence gate passes.
