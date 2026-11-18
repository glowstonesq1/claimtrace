# Eval case schema (v1)

Cases live in `evals/datasets/<suite-set>/<suite>.jsonl`, one JSON object per line.

## Common fields

```json
{
  "id": "ext-001",
  "suite": "extraction",
  "description": "one line, what is being tested",
  "documents": [
    {"key": "a", "title": "Services Agreement", "doc_type": "contract",
     "text": "markdown text; use '## 2. Delivery' headings and '2.1 ...' numbered clauses",
     "amends": null}
  ]
}
```

`doc_type` ∈ contract, amendment, sow, proposal, policy, audit_report, evidence, report, other.
`amends` is the `key` of the document an amendment amends (amendment documents only).
Parties should be introduced the way contracts do: `Acme Ltd (the "Supplier")`.

Matching rule used everywhere: a gold `*_contains` string matches a system item
when the gold string, after lowercasing and whitespace collapsing, is a substring
of the system item's quote (or the quote is a substring of it).

## Suite-specific fields

| suite | extra fields |
|---|---|
| `extraction` | `gold_commitments`: list of `{quote_contains, type, obliging_party, modality}`. `type` ∈ obligation, entitlement, prohibition, condition, deadline, consequence, service_level. `obliging_party` is the defined alias as written (e.g. `"Supplier"`) or `null` if none is stated. `modality` ∈ must, must_not, may, reasonable_efforts. Also `max_extra`: integer, how many extra (unlabelled) commitments are tolerated before they count as false positives (default 0). |
| `deadline` | `gold`: `{quote_contains, deadline_kind, date, offset_days, business_days, anchor_contains, has_condition, has_exception}`. `deadline_kind` ∈ absolute, relative, recurring, vague, none. Use `null` for non-applicable fields. |
| `consistency`, `contradiction`, `evidence_gap`, `amendment` | `base_key`, `other_key`, `checks`: list of `{subject_quote_contains, gold_verdict}` where `subject_quote_contains` identifies a commitment in the base document and `gold_verdict` ∈ consistent, contradicted, partially_supported, not_addressed, ambiguous, needs_human_review. The `amendment` suite also has `gold_effects`: list of `{section, effect}` with `effect` ∈ in_force, replaced, deleted. |
| `qa` | `question`, `gold_status` ∈ stated, implied, contradicted, not_addressed, ambiguous, needs_human_review; `gold_citation_contains`: list of strings that must each match some cited quote (empty list when `not_addressed`). |
| `ambiguous` | `gold`: `{quote_contains, expect_review: true, max_confidence}` with `max_confidence` ∈ medium, low, unknown. |

Notes on verdicts, so labels are consistent:

- `contradicted`: the other document states a different value or the opposite
  (different date, amount, place, modality, or a measured value that fails the
  committed level). Amendments that change a term count as `contradicted`.
- `partially_supported`: the other document supports part of the commitment and
  states an exception, gap, or shortfall for another part.
- `not_addressed`: the other document says nothing relevant, or explicitly
  says it did not test the matter.
- `consistent`: the other document states the same value/fact. For evidence
  documents this means only "matching evidence text was located".
- `ambiguous` / `needs_human_review`: genuinely unclear wording, or the
  relevant text is too vague to compare.
