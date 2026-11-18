# ML researcher
## Top 3 concerns
- §8/§12 benchmark leakage: the same team writes synthetic docs, labels, and the rules extractor. "Disclose the bias" does not fix it, because rules will be tuned to the generator's phrasing ("shall deliver ... no later than"). Reported P/R will be inflated, and an LLM compared against it will look worse than it is.
- §8 "span-overlap matching" is undefined. Without a threshold (IoU, containment, or normalised-text match) and a rule for splitting or merging compound clauses ("shall X and Y"), P/R can swing 10-20 points. Same for deadline accuracy and citation P/R.
- §5/§8 contradiction detection is only illustrated by date change (J4). Real conflicts are negation or modality ("shall" vs "may"), scope or quantifier ("all" vs "material"), party swaps, and carve-outs in amendments. The pairing step ("matching was weak") is unspecified, and BM25 on commitments will miss paraphrases, so recall is silently lost.
## Top 3 recommendations
- Build the held-out set from non-team text (CUAD / public-domain contracts, SEC exhibits, even 20 passages) plus adversarial cases written by someone who has not seen the rules. Freeze it, and report rules-vs-LLM only on it. I disagree with deferring external cases to v1.0 because the baseline number is meaningless before then.
- Fix the metrics in `evaluation.md` before coding: a commitment matches if normalised quote containment is >= 0.5 and the obliging party agrees, with one-to-one matching. Report strict and lenient variants. Use bootstrap 95% CIs and paired tests (McNemar / paired bootstrap) for comparisons.
- Make verify a pipeline of candidate pairing (BM25 plus party, section and type keys), then a typed comparison of normalised fields (date, amount, modality, polarity, party). Only the residue goes to NLI or an LLM, and an LLM-only verdict is capped at needs_human_review unless both quotes verify.
## Must-have v0.1 requirements
- ~120 cases give wide intervals (n=40 per suite gives about ±15 points). Report CIs, make no "A beats B" claims inside the CI, and publish per-suite counts.
- Calibration is bucket accuracy with categorical confidence. Report it per bucket with n, and drop the term "calibrated" unless high-bucket precision is measurably above low-bucket.
- Run the rules baseline against a trivial baseline (keyword "shall/must" sentence split) so that "rules" has a floor to beat.
- Hallucination checks cover not-found cases: at least 25% of QA cases have gold not_addressed, including near-miss distractors.
- Record the model version, prompt hash and seed in each run. LLM results are non-deterministic, so use three runs and report the variance.
## Defer (and why)
- Dense retrieval and hybrid (§3, v0.2): agreed, but only after the eval logs retrieval recall@k. Add that metric now, otherwise "where lexical fails" cannot be known.
- A fine-tuned NLI model: a distraction at this data size. Use rules plus an optional LLM judge.
- Probabilistic confidence or ECE: meaningless at n≈120.
## Failure modes to test
- Negation, modality and scope flips ("shall not" vs "shall", "may" vs "shall", "all" vs "material").
- Amendments that delete or restate a clause without a number or date change.
- Cross-references ("subject to §9.2"), and definitions that alter an obligation's meaning.
- A compound sentence that yields two commitments gold-labelled as one, with the span-match rule deciding the score.
- Paraphrased or different-vocabulary clauses that BM25 does not pair, so the contradiction is silently reported as consistent or not_addressed.
- Prompt injection inside a quoted clause, plus a quote that exists verbatim but in an unrelated passage.
