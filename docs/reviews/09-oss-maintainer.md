# Open-source maintainer
## Top 3 concerns
- License is unstated anywhere in the spec (§12 only mentions dataset licenses). PDF text-layer parsing (§3.1) will tempt PyMuPDF (AGPL-3.0), which would make the whole API effectively AGPL and block corporate adoption and Docker redistribution. Nobody has audited dependency licenses.
- Maintenance burden: §10 says one Python distribution but the "seven packages" layout is kept, plus a React app, eval suite, Docker Compose, and 3 LLM paths (rules/openai/ollama). That is 2-3 contributors' worth of surface area; the bus factor is ~1 ("owner: maintainers").
- Stars vs real users: the eval honesty rule (§8) is a differentiator, but the README promise of "published baseline, including where it is bad" with a self-authored synthetic benchmark invites drive-by stars and zero retention. Real users need a demo on their own PDFs in under 5 minutes, which a weak rules extractor may not deliver.
## Top 3 recommendations
- I disagree with leaving license open. Choose Apache-2.0 (patent grant matters for document AI), use pypdf/pdfminer.six (MIT/BSD) or pypdfium2 (Apache/BSD), and add a CI license check (pip-licenses or REUSE) that fails on GPL/AGPL. If AGPL parsing is ever wanted, make it an optional extra with a loud notice.
- Ship one distribution with one version number and one changelog (release-please, SemVer, 0.x with an explicit "API unstable" note). The risk of separate package versions is a release matrix nobody maintains.
- Keep CI cheap: LLM-backed evals never run on PRs; only the rules suite and a `fake` provider run in CI. Nightly or manual workflow for model evals, with results committed.
## Must-have v0.1 requirements
- LICENSE, NOTICE, SBOM/third-party license table, DCO or CLA decision, SECURITY.md, CODE_OF_CONDUCT.
- CONTRIBUTING with a one-command dev setup (`make dev`) that works offline, and a pinned lockfile.
- 8-10 labelled good-first-issues with files named and acceptance tests: e.g. add an eval case, a new date format, a DOCX edge case. Not "improve UI".
- Bundled sample documents plus a seeded demo so first run shows value with zero uploads; sample data licensed CC0.
- Docker image tags and PyPI release automated from tags, with a tested upgrade path for the SQLite schema (migrations from day one).
## Defer (and why)
- Plugin API and extractor registry (§11 v1.0): it freezes interfaces before anyone has used them.
- Postgres adapter and any second Store: contributors will request them; saying no early saves maintainer time.
- URL ingestion (§3.1): the SSRF surface generates security reports for a maintainer team that cannot triage them; keep it off or cut it from v0.1.
- Embeddings (v0.2): adds model download and licensing questions (model weights licenses).
## Failure modes to test
- Fresh clone on Windows/macOS/Linux: install and first analyze under 10 minutes without an API key.
- CI license gate catching a transitive AGPL/GPL dependency introduced by a PR.
- Contributor PR adds an eval case that changes the published baseline; confirm the baseline-update process is documented and reproducible.
- Docker image size and build time with the web app; a broken Node toolchain should not block API-only contributors.
