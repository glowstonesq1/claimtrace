# v0.2 development run: core set, rules system

Not a published result. `core` is the set used for error analysis while developing, so these numbers
show that v0.2 did not regress and that the new amendment handling covers core's drafting; they say
nothing about generalisation. The generalisation claim waits for the sealed amendment set
(`amendments-v2`) and the holdout, which the engine work never opened.

Reproduce: `claimtrace eval run --suite core --model rules --out evals/runs/dev` (commit in `manifest.json`).

| Metric | v0.1 published (`published/v1-core-rules`) | this run |
|---|---|---|
| Verification accuracy — amendment | 0.89 [0.75–1.00] (n=28) | 1.00 [1.00–1.00] (n=28) |
| Amendment effect accuracy | 0.87 [0.74–0.97] (n=31) | 0.97 [0.90–1.00] (n=31) |
| Verification accuracy — all suites | 0.75 | 0.77 |

All other metrics are unchanged. The one remaining amendment-effect miss is a clause that holds no
commitment ("This Agreement continues for an Initial Term of 3 years"), so there is no commitment whose
effect can be shown.
