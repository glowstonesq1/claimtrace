# Amendment dev fixtures

Hand-written development cases for amendment parsing and application (v0.2). They were written from
scratch for unit tests and are **not** copied from, or derived from, any evaluation dataset. Tune against
these and `evals/datasets/core` only; sealed sets are never read.

Each `*.case` file has three parts separated by marker lines:

```
=== base ===
<Markdown of the original document>
=== amendment ===
<Markdown of the amending document>
=== expected ===
<JSON>
```

Expected JSON keys:

- `effects`: section number of a base commitment -> expected `document_effect` (`in_force`, `replaced`, `deleted`).
- `actions` (optional): expected instruction actions, in document order.
- `unresolved` (optional, default 0): number of instructions that must be flagged for human review.
- `verdicts` (optional): list of `{subject_contains, verdict}` expected from `verify_documents(base, amendment)`.
- `derived_contains` (optional): text that must appear in some in-force amended wording.
- `amendment_type` (optional, default `amendment`): `doc_type` of the amending document.
