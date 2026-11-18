# Launch plan (v0.1.0)

## Positioning (from the design review)

Lead with one job: **"Did the amendment change it, and are we still on track?"** (amendment drift plus
evidence). Do not lead with "AI contract analysis". Say plainly what it is not: legal advice, a CLM system,
or a chatbot.

**Honest caveat to carry into every channel:** amendment handling generalised worst on the sealed holdout
(0.61). Present the evaluation as a strength: we publish numbers, including where we are weak, and invite
help on exactly that.

## GitHub (week 0)

- [ ] Repository public with README screenshots, a ~60 s screen recording (load samples → register → ask →
      verify), topics: `contracts`, `document-ai`, `rag`, `provenance`, `self-hosted`, `compliance`.
- [ ] v0.1.0 release with notes ([docs/releases/v0.1.0.md](releases/v0.1.0.md)) and a Docker image.
- [ ] Ten good first issues filed from [good-first-issues.md](good-first-issues.md); pin "Help us beat the
      holdout: amendment patterns".
- [ ] Discussions enabled: "Show your eval run" and "Document types you need".

## Technical blog post (week 1)

Working title: *"We wrote a benchmark our own code wasn't allowed to see."* Outline:
1. The problem: "hallucination-free" legal tools still mis-cite (cite the Stanford study from research.md).
2. Design: quotes as offsets, verified twice; amendments never overwrite; abstain over guess.
3. The protocol: blind core set → frozen baseline → error analysis → sealed holdout.
4. Results, including what failed (amendment generalisation) and that a constant guess ties us on consistency.
5. What's next and how to contribute cases.
Cross-post to the Python and self-hosted communities; submit to Hacker News as "Show HN" with the eval table
in the first comment.

## Early pilot users (weeks 1–6)

Target 5–8 pilots: two procurement or operations teams at 20–200-person companies, two internal audit or
compliance practitioners, one project-management office, and two developers building document tools.

- Offer: a 30-minute setup call, then two weeks of use on their own (non-confidential or self-hosted)
  documents.
- Measure: time to first useful register (target under 5 minutes), share of items flagged for review (target
  under 30%), false clears found by the pilot (target 0), and "would you keep using it?"
- Ask each pilot for 5–10 anonymised clauses we got wrong. These become a new sealed set (with consent and
  synthetic rewriting).
- Exit criteria for v0.2 priorities: re-rank the roadmap using pilot failure reports.

## Risks during launch

| Risk | Response |
|---|---|
| Read as legal advice | Banner and report wording; decline "is this enforceable?" requests in issues. |
| A security report on URL ingestion | It is off by default; follow SECURITY.md and publish an advisory. |
| "Why not just use ChatGPT?" | Point to the verified-quote guarantee, the amendment register and the published false-clear rate. |
