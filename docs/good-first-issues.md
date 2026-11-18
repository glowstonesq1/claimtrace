# Good first issues

Each issue names the files to touch and an acceptance test. Copy one into a GitHub issue with the
`good first issue` label.

1. **Add UK and EU cities to the place gazetteer.**
   Files: `packages/verification/compare.py` (`PLACES`). Accept: a new test in `tests/test_verification_and_ask.py`
   shows "Leeds" vs "Wakefield" compared as two UK places (still `consistent` at country level) and
   "Leeds" vs "Lyon" as `contradicted`.
2. **Recognise "within thirty (30) calendar days" with the number word first.**
   Files: `packages/extraction/patterns.py`. Accept: `extract_deadline("within thirty (30) calendar days of receipt")`
   returns `kind="relative", offset_days=30`; add the case to `tests/test_core.py`.
3. **Amendment pattern: "Clause X is amended by deleting 'A' and inserting 'B'".**
   Files: `packages/extraction/amendments.py`. Accept: unit test that it parses as `modify` with old and new text,
   and `apply_amendments` marks the base clause `replaced`. Do not look at `evals/datasets/holdout`.
4. **Show the egress log in the UI** (a "Privacy" panel on the Documents page).
   Files: `apps/web/src/Library.tsx`, `apps/web/src/api.ts`. Accept: the panel lists host, bytes and time from
   `GET /privacy/egress`, and the E2E smoke test still passes with no axe violations.
5. **Keyboard shortcut to move between findings on the Verify page** (`j`/`k`).
   Files: `apps/web/src/AskVerify.tsx`. Accept: focus moves to the next/previous finding heading; shortcuts are
   listed in a visible help line; they do nothing while typing in an input.
6. **Add `--format csv` to `claimtrace eval report`.**
   Files: `packages/evaluation/runner.py`, `packages/cli/main.py`. Accept: one row per metric with value, CI low,
   CI high, n; a test in `tests/test_eval.py`.
7. **Detect DOCX tracked changes and warn.**
   Files: `packages/ingestion/parsers.py`. Accept: a DOCX with `w:ins`/`w:del` produces a document warning
   "contains tracked changes; deleted text is not shown"; test with a generated file.
8. **Report dataset licence and author in the eval manifest.**
   Files: `evals/datasets/*/README.md` (new), `runner.py`. Accept: `manifest.json` includes them.
9. **Dark-mode screenshot in the README** and a contrast check of the dark palette (WCAG AA).
   Files: `apps/web/src/styles.css`, `README.md`. Accept: axe passes with `prefers-color-scheme: dark` emulated
   in `e2e/smoke.mjs`.
10. **Write five new extraction eval cases from a public-domain contract** (e.g. a government template).
    Files: `evals/datasets/core/extraction.jsonl`. Accept: cases validate against `evals/SCHEMA.md`; the source
    and its licence are cited in the case description.
