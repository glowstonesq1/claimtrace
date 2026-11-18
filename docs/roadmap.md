# Roadmap

Priorities come from the [v0.1 evaluation](evaluation.md) and the [design review](design-review.md). Dates
are intentionally absent: this is a volunteer project and items ship when they pass their eval gate.

## v0.2 — "Read more, generalise better"

Gate for every item: no regression on the sealed holdout, and a **new** sealed set for anything tuned.

1. **Amendment generalisation** (top priority). The holdout showed 0.61 verdict / 0.50 effect accuracy.
   Add drafting patterns ("is amended by deleting", "shall be read as", schedules replaced wholesale,
   restated agreements), a model-assisted fallback whose output must still match a section in the base
   document, and a fresh amendment-only sealed set of at least 40 cases.
2. **External held-out benchmark**: CUAD-derived cases (CC BY 4.0) for extraction, so no number depends
   only on agent-written data.
3. **LLM baselines**: publish `ollama:` and `openai:` runs with `--repeats 3` and variance.
4. **OCR** for scanned PDFs (Tesseract, optional extra) with per-page confidence.
5. **Hidden-text detection** in PDFs (white or tiny text, off-page) and DOCX hidden runs (red-team finding).
6. **Hybrid retrieval** (local embeddings, optional) once retrieval recall@k is logged by the eval runner.
7. **Tables**: keep table structure from DOCX and PDF; compare schedule tables cell by cell.
8. **Business-day calendars** (configurable holidays) so "10 Business Days" becomes a date.
9. **Hash-pinned Python lockfile** and blocking `pip-audit` in CI.
10. **ICS export** of deadlines (user-initiated download only).

## v1.0 — "Team use"

- Accounts, roles and a separation between preparer and reviewer; signed review trail (hash chain).
- Postgres adapter behind the existing `Store` seam; background job queue for large corpora.
- Order-of-precedence and "notwithstanding" resolution across document families.
- Plugin interface for extractors and comparators (only after two real external extractors exist).
- Interactive relationship graph (keyboard accessible) on top of the existing graph API.
- Packaged desktop build for non-technical users.

## Explicitly not planned

Legal advice or risk scores; automatic notices, emails or contract edits; public web fact-checking;
generic enterprise search.
