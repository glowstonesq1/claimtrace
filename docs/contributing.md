# Contributing

Thanks for helping. ClaimTrace values **correct, auditable behaviour over features**, so every change needs a
test, and anything that changes extraction or answers needs an eval run.

## Set up

```bash
make dev        # Python venv + package + web build (Python 3.11+, Node 20+)
make test       # unit, API, security and privacy tests (offline)
make lint typecheck
make eval       # full core benchmark with the rules engine (~2 s)
```

Run the UI with `make serve`. For frontend work, `cd apps/web && npm run dev` proxies API calls to port 8000.

## Ground rules

- **Model output is untrusted input.** Validate it with Pydantic and locate every quote with
  `core.text.find_quote` before storing it. Never trust offsets a model reports.
- **No silent guesses.** If extraction is unsure, set `needs_review` with a plain-English reason.
- **Never log document text, questions, notes or filenames.** Log IDs and counts.
- **No new network egress** without a setting that defaults to off, plus a test.
- **No GPL/AGPL runtime dependencies** (CI enforces this). Prefer the standard library and existing deps.
- **Don't open `evals/datasets/holdout/`** when working on extraction or verification. It is how we know a fix
  generalises. If you need more data, add cases to `core`.
- Published eval runs under `evals/runs/published/` are never edited. Add a new run directory instead.
- UI copy is plain language (see `apps/web/src/labels.ts`); keep status shown as text and icon, not colour alone.

## Pull requests

1. Open an issue first for anything larger than a bug fix.
2. Include tests. For extraction or verification changes, paste the before/after `claimtrace eval report`
   table for `core` in the PR.
3. Keep PRs focused; one behaviour change per PR.
4. Sign off your commits (`git commit -s`, Developer Certificate of Origin).

## Maintainer expectations

Maintainers aim to triage new issues within one week and review PRs within two. Security reports follow
[SECURITY.md](../SECURITY.md). Releases follow semantic versioning; during 0.x the API may change between
minor versions and changes are listed in [CHANGELOG.md](../CHANGELOG.md).
