# Evaluation

ClaimTrace publishes its numbers, including the bad ones. This page defines every metric, describes how
the benchmark was built and protected from the people who wrote the system, and reports the v0.1 baseline.

## TL;DR (v0.1.0, rules baseline, no language model)

- **Grounding holds**: 0.00 hallucination rate and 1.00 "not found" recall on both sets; every quote is
  verified against stored text by construction.
- **Rarely gives a false all-clear**: false-clear rate 0.03 on the sealed holdout, against 0.29 for the
  keyword floor.
- **Contradiction detection generalises**: precision/recall 0.82 / 0.64 on the holdout (0.87 / 0.65 on the
  set used for error analysis).
- **Amendment handling did not generalise** (0.61 verdict accuracy, 0.50 effect accuracy on the holdout,
  versus 0.89 / 0.87 on the error-analysis set). The amendment-instruction patterns are overfitted to the
  drafting styles in the core set. This is the top item on the [roadmap](roadmap.md).
- **On the consistency suite the rules do not beat a constant "consistent" guess** (0.81 vs 0.76 on the
  holdout, overlapping intervals). The value is in contradictions and in not giving false clears.
- **Finding commitment sentences is easy; attributes are where ClaimTrace adds value**: the keyword floor
  reaches similar recall, but party attribution (0.97 vs 0.69) and deadline parsing (0.83 vs 0.00) differ.
- Sample sizes are small (46 holdout cases). Intervals are wide; do not read differences inside them as real.

## Benchmark construction

| Set | Cases | Written by | Seen by the system's authors before scoring? |
|---|---|---|---|
| `evals/datasets/core` | 140 (30 extraction, 20 deadline, 20 consistency, 20 contradiction, 20 QA, 10 evidence gap, 10 amendment, 10 ambiguity) | An isolated agent instructed not to read the system's code, working only from `evals/SCHEMA.md` and the spec | No for the first run (frozen as `v1-blind-baseline-rules`). **Yes afterwards**: it was used for error analysis. |
| `evals/datasets/holdout` | 46 (8/6/6/6/8/4/4/4) | A second isolated agent, new companies, industries and drafting styles | **No.** Opened only by the runner, after the code was frozen at commit `1899c3c`. |

All documents are fictional and synthetic. No real contracts were used.

**Known bias.** Both sets were written by language-model agents from the same project brief, and the
label conventions in `evals/SCHEMA.md` were written by the system's authors. Neither set is a substitute
for real contracts reviewed by practitioners. Comparative claims (e.g. "the LLM extractor beats rules")
require an external held-out set (roadmap: CUAD-derived cases, CC BY 4.0).

## Protocol

1. Freeze metric definitions (below) before tuning. *(Done in commit history before the first run.)*
2. Run the blind core set once; freeze it as `evals/runs/published/v1-blind-baseline-rules`.
3. Error analysis on the core set, restricted to error *categories* (confusion matrices) and a handful of
   examples per category. Fixes had to be general (e.g. "clauses on consecutive lines were merged into one
   passage"), not case-specific. Each fix is a separate commit.
4. Commission the sealed holdout set while fixing; never open it.
5. Freeze code, run core + holdout + the keyword floor; publish all runs unchanged.

### Fixes made during error analysis (between the blind and post-analysis core runs)

| Fix | General cause | Effect on core |
|---|---|---|
| Split numbered clauses on consecutive lines in Markdown/TXT | Ingestion merged "4.1 …\n4.2 …" into one passage | amendment 0.68→0.89, effects 0.45→0.87, party 0.85→0.97 |
| Pair against every sentence in the other document, not only its commitments | Schedules/policies state terms without modal verbs | contradiction 0.29→0.65, consistency 0.42→0.74 |
| Check obligation strength (shall vs may) before numbers | Matching numbers masked a modality change | contradiction recall |
| Stable stemming ("deliver/delivered", "invoice/invoices") | Inconsistent suffix stripping | pairing and QA |
| IDF-weighted coverage, expected-answer-type check, remove the "may be relevant" band | Weak lexical matches presented as answers | hallucination 0.20→0.00 |
| QA coverage threshold 0.5 | Chosen on the core set: no not-found case scored above 0.45 | QA 0.55→0.60 |
| Lower-case company suffixes ("Freight plc") in party names | Party name capture required capitals | party attribution |

## Results

| Metric | Core, blind (before fixes) | Core, after error analysis | **Holdout (sealed)** | Keyword floor (holdout) |
|---|---|---|---|---|
| Commitment precision | 0.99 (0.98–1.00) n=29 | 0.96 (0.89–1.00) n=30 | 1.00 (1.00–1.00) n=8 | 1.00 (1.00–1.00) n=8 |
| Commitment recall | 0.95 (0.91–0.99) n=29 | 0.96 (0.92–0.99) n=29 | 0.88 (0.72–1.00) n=8 | 0.87 (0.70–0.97) n=8 |
| Party attribution | 0.85 n=145 | 0.97 n=146 | 0.97 n=36 | 0.69 n=35 |
| Commitment type | 0.89 n=145 | 0.92 n=146 | 0.92 n=36 | 0.80 n=35 |
| Deadline (kind + value) | 0.70 (0.50–0.90) n=20 | 0.80 (0.60–0.95) n=20 | 0.83 (0.50–1.00) n=6 | 0.00 (0.00–0.00) n=6 |
| Condition detection | 0.75 (0.55–0.95) n=20 | 0.85 (0.70–1.00) n=20 | 1.00 (1.00–1.00) n=6 | 0.83 (0.50–1.00) n=6 |
| Exception detection | 0.85 (0.70–1.00) n=20 | 0.90 (0.75–1.00) n=20 | 1.00 (1.00–1.00) n=6 | 0.83 (0.50–1.00) n=6 |
| Verification: consistency suite | 0.33 (0.19–0.47) n=43 | 0.74 (0.60–0.86) n=43 | 0.81 (0.62–0.95) n=21 | 0.76 (0.57–0.91) n=21 |
| Verification: contradiction suite | 0.29 (0.13–0.45) n=31 | 0.65 (0.48–0.81) n=31 | 0.61 (0.39–0.83) n=18 | 0.39 (0.17–0.61) n=18 |
| Verification: evidence-gap suite | 0.41 (0.23–0.64) n=22 | 0.73 (0.55–0.91) n=22 | 0.82 (0.55–1.00) n=11 | 0.36 (0.09–0.64) n=11 |
| Verification: amendment suite | 0.68 (0.50–0.86) n=28 | 0.89 (0.75–1.00) n=28 | 0.61 (0.31–0.85) n=13 | 0.00 (0.00–0.00) n=13 |
| Amendment effect (replaced/deleted/in force) | 0.45 (0.29–0.61) n=31 | 0.87 (0.74–0.97) n=31 | 0.50 (0.21–0.71) n=14 | – |
| False-clear rate ↓ | 0.07 n=124 | 0.08 n=124 | 0.03 n=63 | 0.29 n=63 |
| QA status accuracy | 0.50 (0.30–0.75) n=20 | 0.60 (0.35–0.80) n=20 | 0.88 (0.62–1.00) n=8 | 0.50 (0.12–0.88) n=8 |
| Citation recall | 0.85 (0.61–1.00) n=13 | 0.39 (0.15–0.61) n=13 | 0.62 (0.25–1.00) n=4 | 0.00 (0.00–0.00) n=8 |
| Citation precision | 0.77 (0.54–0.96) n=13 | 0.39 (0.15–0.61) n=13 | 0.75 (0.25–1.00) n=4 | 0.00 (0.00–0.00) n=8 |
| 'Not found' recall | 0.43 (0.14–0.71) n=7 | 1.00 (1.00–1.00) n=7 | 1.00 (1.00–1.00) n=4 | 0.00 (0.00–0.00) n=4 |
| 'Not found' precision | 0.75 (0.25–1.00) n=4 | 0.47 (0.20–0.73) n=15 | 0.80 (0.40–1.00) n=5 | – |
| Hallucination rate ↓ | 0.20 (0.05–0.40) n=20 | 0.00 (0.00–0.00) n=20 | 0.00 (0.00–0.00) n=8 | 0.50 (0.12–0.88) n=8 |
| Ambiguity flagged | 0.80 (0.50–1.00) n=10 | 1.00 (1.00–1.00) n=10 | 0.50 (0.00–1.00) n=4 | 0.00 (0.00–0.00) n=4 |
| Review burden (share flagged) | 0.05 n=150 | 0.09 n=151 | 0.19 n=36 | 0.00 n=35 |
| Contradiction detection P / R | 0.533 / 0.258 (n=31) | 0.87 / 0.645 (n=31) | 0.818 / 0.643 (n=14) | None / 0.0 (n=14) |
| Latency per case p50 / p95 (ms) | 4.4 / 7.1 | 4.2 / 5.9 | 4.8 / 7.9 | 0.0 / 1.8 |
| Cases | 140 | 140 | 46 | 46 |

Intervals are bootstrap 95% CIs over cases (1,000 resamples, fixed seed). "n" is the number of cases, checks
or matched items the metric is computed over. Raw per-case outputs, gold labels and predictions are in each
run's `cases.jsonl`; versions and the dataset hash are in `manifest.json`.

### What the keyword floor is

`--model keyword`: every sentence with *shall/must/will/may* is a commitment owed by the last capitalised
word before the verb; no deadlines, conditions or review flags; every verification check answers
"consistent"; every question is answered as "stated" with no citations. It exists so that each number has
a trivial comparison.

## Metric definitions

| Metric | Definition |
|---|---|
| Commitment precision / recall | Per case, gold and system commitments are matched one-to-one: a gold item matches a system item when its `quote_contains` string (lower-cased, whitespace-collapsed) is a substring of the system quote or vice versa; ties prefer same modality, then same type. Unmatched system items beyond `max_extra` are false positives. Reported as the mean over cases (with CI) and micro-averaged. |
| Party attribution | Among matched commitments, share whose `obliging_party` equals the gold alias (case-insensitive, leading "the" ignored; null = null). |
| Commitment type | Among matched commitments, share with the gold `type`. |
| Deadline accuracy | The commitment containing the gold quote has the gold `deadline_kind` and, where given, the same date (absolute) or offset + business-day flag + anchor substring (relative). |
| Condition / exception detection | Whether the system found any condition (exception) agrees with `has_condition` (`has_exception`). |
| Verification accuracy | For each check, the finding whose subject contains `subject_quote_contains`; its verdict must equal the gold verdict. A missing finding counts as wrong. |
| Amendment effect | For each `gold_effects` section, the base commitment's `document_effect`. |
| Contradiction detection P / R | Over all verification checks, "contradicted" as the positive class. |
| False-clear rate | Share of checks predicted "consistent" whose gold is contradicted or partially supported. The error the design review ranked most dangerous. |
| QA status accuracy | Answer status equals gold status. |
| Citation recall / precision | Recall: share of gold citation strings matched by some cited quote. Precision: share of cited quotes (supports, conflicts, context roles) matching some gold string. Only on cases with gold citations. |
| "Not found" recall / precision | Recall over gold not_addressed cases; precision over predicted not_addressed. |
| Hallucination rate | Share of QA cases where any citation fails verbatim verification **or** the system answers (status ≠ not_addressed) a case whose gold is not_addressed. |
| Ambiguity flagged | For ambiguous-language cases, the commitment is flagged for review and its confidence is at or below `max_confidence`. |
| Calibration | Precision (extraction) or accuracy (QA) per confidence label. The labels are categorical and rule-derived; we do not compute ECE (n is too small and there are no probabilities). |
| Review burden | Share of extracted commitments flagged for human review. |
| Latency / cost | Wall-clock per case (single process, in-memory SQLite). Cost is zero for rules; LLM runs record bytes sent in the egress log. |

Calibration note: extraction precision by label is high 0.99 (n=118), medium 0.95 (n=22), low 1.00 (n=8)
on the post-analysis core run, and 1.00 for every label on the holdout. The labels are therefore **not**
separating correct from incorrect extractions yet; they
reflect wording risk (exceptions, vague timing), not error probability. Read them as "how carefully to read
this", which is how the UI words them.

## Reproduce

```bash
claimtrace eval run --suite core --model rules
claimtrace eval run --suite holdout --model rules
claimtrace eval run --suite core --model keyword
claimtrace eval report --format markdown        # latest run
```

With a model (results are non-deterministic; use `--repeats 3` and report the spread):

```bash
CLAIMTRACE_LLM_BASE_URL=http://localhost:11434/v1 claimtrace eval run --suite holdout --model ollama:llama3.1 --repeats 3
CLAIMTRACE_LLM_API_KEY=... claimtrace eval run --suite holdout --model openai:<model> --repeats 3
```

No LLM baseline is published for v0.1: the release environment had no model available. Contributions of
LLM runs (with `manifest.json`) are welcome; see [contributing](contributing.md).

## Adding cases

Follow `evals/SCHEMA.md`. New cases go to `core` (development) unless you did not look at the code, in which
case propose them for a new sealed set. Changing a published number requires a new run directory, never an
edit to an existing one.
