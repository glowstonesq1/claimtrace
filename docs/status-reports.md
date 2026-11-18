# Phase status reports (v0.1 build, 2026-11-18)

Each report: completed · changed assumptions · risks · next steps · open questions.

## Phase 1 — Research and product definition
- **Completed:** `docs/research.md` (74 sources, access-dated; two sources only reachable via search
  snippets, marked) and `docs/product-spec.md`.
- **Changed assumptions:** PyMuPDF and Marker are licence risks for an Apache-2.0 project, so pypdf and python-docx
  were chosen. Even leading legal AI tools mis-cite, so quote verification is done by our code, never trusted from a
  model.
- **Risks:** no public benchmark for contract-vs-amendment or contract-vs-audit conflicts.
- **Next:** design review. **Open:** default model for the recommended setup.

## Phase 2 — Multi-agent design review
- **Completed:** 11 isolated reviewer agents (`docs/reviews/`), synthesis with 24 decisions, backlog, rejected
  ideas, risk register and definition of done (`docs/design-review.md`).
- **Changed assumptions:** lead with amendment drift; split status into document effect and human-set
  lifecycle; evidence ≠ sufficiency; Vite SPA instead of Next.js; graph shown as an accessible table; 4 screens.
- **Risks:** benchmark leakage (same authors as system) → mitigated by blind and sealed agent-written sets.
- **Next:** architecture and vertical slice.

## Phase 3 — Architecture
- **Completed:** monorepo layout as briefed, one `claimtrace` distribution mapped onto `packages/*` and
  `apps/api`; seams only for `Store` and `LLMProvider`.
- **Changed assumptions:** no Postgres or graph-DB adapter yet (no second implementation exists to justify the
  seam beyond `Store`).
- **Open:** whether to split packages for separate publishing later (not needed for v0.1).

## Phase 4 — MVP implementation
- **Completed:** ingestion (sandboxed), rules extraction, amendment application, graph, Q&A, verification,
  reports, API, CLI, web UI.
- **Changed assumptions:** "consistent" vs "not_addressed" for untouched clauses in amendment mode follows the
  blind annotator's convention (not_addressed). The verbatim check cannot stop injected text that is really in the
  document, so a heuristic detector and flags were added.
- **Risks:** amendment patterns overfit (confirmed in Phase 5).

## Phase 5 — Evaluation
- **Completed:** 140-case blind core set, 46-case sealed holdout, runner, published runs (blind baseline,
  post-analysis, holdout, keyword floor).
- **Changed assumptions:** a constant "consistent" guess ties the rules on the consistency suite; keyword
  matching finds commitment sentences nearly as well; attributes are where value is added.
- **Risks:** amendment generalisation (0.61/0.50 on holdout); small n.
- **Next:** v0.2 amendment work against a new sealed set. **Open:** LLM baseline (no model was available).

## Phase 6 — Quality, security, developer experience
- **Completed:** 86 Python tests (unit, API, file security, SSRF, privacy, LLM boundary, eval smoke), browser E2E
  with axe on all four screens, ruff, mypy (core), web typecheck, CI workflow, Docker Compose (loopback only,
  non-root, read-only).
- **Not verified here:** Docker image build (no Docker daemon in the build environment); GitHub Actions run (no
  remote repository yet).
- **Risks:** no hash-pinned Python lockfile; heuristic injection detection; hidden PDF text.

## Phase 7 — Open-source readiness
- **Completed:** README, docs set, LICENSE (Apache-2.0), NOTICE, SECURITY, CODE_OF_CONDUCT, CHANGELOG, release
  notes, issue/PR templates, good first issues, roadmap, launch plan, sample outputs.
- **Open:** a conduct contact address and repository URL must be filled in by the maintainers.
