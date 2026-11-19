# Project journey

A short history of what each version delivered, and how the numbers were kept honest. For every change in
detail, see the [changelog](../CHANGELOG.md).

## v0.1: the engine and its first numbers

The first release was a local-first engine and a small web app. It reads a contract, its amendments and
related documents (audit reports, delivery records), lists who owes what to whom and by when, answers questions
only with quotes it has checked against the source, and checks one document against another. It works fully
offline with a rules engine; an optional language model can help, but its output is checked by code before it is
used. Before any code was written, the design was reviewed from product, legal, audit, security, privacy and
end-user angles. That review set the design decisions listed in [architecture.md](architecture.md#9-design-decisions).

## v0.2: better at amendments

The v0.1 numbers showed one clear weakness: amendment wording the engine had not seen before. v0.2 added many
more amendment patterns, plus hidden-text detection, business-day deadlines, calendar (ICS) export, optional OCR
for scanned PDFs, DOCX tables and a hash-chained review trail.

## v0.3: use it without installing

v0.3 made ClaimTrace usable without a local install: a page that runs the real engine in the browser with
nothing uploaded, a skill for claude.ai, a plugin for Claude Code, and an evidence page with every published
number and every case that can be shown. The engine was unchanged.

## v0.4: a clearer website

v0.4 redesigned the website and the README around four questions (what it does, how it decides, how to use it,
how good it is), added an interactive evidence map of the sample documents and a new 50-second film. The engine
was unchanged.

## How the numbers were kept honest

- **Written apart from the code.** The test cases are synthetic and fictional. They were written by a language
  model working from the [label rules](../evals/SCHEMA.md) and the spec, with no access to the engine's code.
  The label rules themselves were written by the project's authors, which is a known bias.
- **Sealed sets.** Besides the 140-case core set used during development, two sets were sealed: a 46-case
  holdout, first opened only by the scoring run after the v0.1 code was frozen, and for v0.2 a 50-case amendment
  set, committed with a checksum manifest before the engine was scored on it. Neither was opened while tuning.
- **A floor to beat.** Scores are shown next to a trivial keyword baseline, with 95% bootstrap intervals.
- **Bad results stay published.** On the v0.1 holdout, amendment verdicts were right only 0.61 of the time. On
  the new amendment set, v0.2 improved verdicts from 0.47 to 0.60, but four in ten are still wrong. On
  consistency checks the rules do not beat a constant "consistent" guess. These numbers are in the README and
  on the website, not just here.
- **Re-scored after fixes.** After the v0.2 review fixes, both sealed sets were re-scored once more; every
  number was identical.

What is still missing: an external held-out set from real contracts and a published language-model baseline.
See the [roadmap](roadmap.md) and the full protocol in [evaluation.md](evaluation.md).
