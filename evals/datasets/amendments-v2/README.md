# amendments-v2 (SEALED)

- Author: a blind agent that never read engine code (`packages/`, `apps/`, `tests/`, `evals/runs/`) and saw only `evals/SCHEMA.md` and one holdout amendment case for the format.
- Date: 2026-11-18
- Status: **SEALED.** Not to be opened by anyone tuning the engine. Score once per release, never iterate against it.
- Contents: `amendment.jsonl` has 50 `amendment`-suite cases in schema v1 (base contract plus amendment; `checks` and `gold_effects`). Fictional parties only.
- Coverage: delete-and-substitute, "shall be read as", deletion by clause or by title, insertions (including 5A), schedule replacement (attached, missing, tabular), amended and restated, numeric-only edits, tables and lists, letter amendments, side letters, renumbering, title-only references, no-op amendments, self-contradiction, non-existent or mismatched references, conditional effectiveness, UK/US spelling and mixed date formats; SaaS, construction, supply, lease, NDA, employment, loan.
- Labelling: conservative. The schema has no rationale field, so each case's `description` states the reason for the less obvious labels. Judgement calls: `v2-ins-03` and `v2-let-02` (partially_supported), `v2-rest-02` (needs_human_review), `v2-date-01` (ambiguous).
- Note: the planning doc `docs/plans/2026-11-18-v0.2.md` did not exist in the checkout, so it was not used.
- Integrity: `MANIFEST.sha256` lists the case file hash; verify with `sha256sum -c MANIFEST.sha256`.
