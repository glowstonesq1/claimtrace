# Privacy and data-governance reviewer

## Top 3 concerns
- §9 "Deletion" lists file, passages, objects, edges, answers, findings. It omits `ReviewDecision` rows (§5) and their free-text notes, which quote contract text and name people. It also omits `evals/runs/<timestamp>/` raw outputs (§8), SQLite free pages and WAL files, BM25 index caches, exported reports, and any LLM provider logs. "Hard delete" is not true until each is covered. Answers citing two documents are "removed" entirely, which silently destroys review history for the other document.
- §9 treats the external LLM provider as an on/off switch visible in `/health`. I disagree because that is not disclosure or consent. Whole passages, and the user's questions, go to OpenAI or any "OpenAI-compatible" endpoint, which in practice is often a third-party proxy. Contracts carry names, addresses, salaries, bank details and signatories. There is no per-document consent, no warning on first send, no record of which documents were sent where, and `Provenance.model` does not capture the endpoint host.
- Data minimisation is absent. §3 and §5 store full text, `author`, `reviewer`, `Party.aliases` and full `Span.quote` copies in several tables, so the same personal data is duplicated and each copy is a separate erasure target. Retention (`CLAIMTRACE_RETENTION_DAYS`) purges "on startup" only, so a long-running container never purges. Retention is also keyed to what, upload time or last access? The spec does not say.

## Top 3 recommendations
- Make erasure a tested invariant: a single delete-cascade function, a post-delete scan that greps the SQLite file (after `VACUUM` and WAL checkpoint) for a canary string from the document, and documented limits. Backups and exports are outside ClaimTrace's control, so say so in the docs. Eval runs must reference synthetic data only, enforced by a CLI refusal to run on user documents.
- Add an explicit egress gate. The first time a provider is used, show the endpoint host and what will be sent. Require a per-document `allow_external_llm` flag (default false). Log the host, document ID and byte count of each send in the local audit table. Offer a redaction pre-pass for emails, phone numbers and IBANs, with the caveat that it is imperfect.
- Ship a one-page data inventory in docs: what is stored where, how long, and what leaves the machine. State that ClaimTrace has no telemetry, with a CI test that fails on any outbound socket during the default test run. Add a self-hoster section on volume location, encryption at rest (document the reliance on disk encryption), and data residency when the LLM endpoint is a US provider.

## Must-have v0.1 requirements
- Delete cascade covers every table including review notes, plus a canary-string test after VACUUM.
- Retention purge runs on a schedule, not only at startup, and its basis is documented.
- External LLM is disabled by default, per-document opt-in, with the endpoint host recorded in `Provenance` and shown in the UI.
- Zero telemetry, zero update checks and zero CDN assets (fonts and scripts bundled), verified by test.
- Logs never contain text, questions or notes, enforced by a log-scrubbing test. Uploaded filenames count as personal data and must be excluded too.

## Defer (and why)
- Field-level encryption and SQLCipher: depends on key management that v0.1 has no user model for. Disk encryption advice is enough for now.
- Automated PII detection and redaction: unreliable, and a false assurance risk. Ship the manual per-document gate first.
- Subject-access and erasure workflows for named individuals: need multi-user context (v1.0). Document the manual SQL route.

## Failure modes to test
- Delete document A after an answer cited A and B: B's data and review history survive, and no fragment of A remains in the DB, the exports or the logs.
- Provider enabled globally, then a document uploaded: confirm nothing is sent without the per-document opt-in.
- Run an LLM extraction against a mock server and assert the request body contains only that document's passages.
- Delete during analyze: no orphaned passages, edges or a half-written run directory.
- Retention purge with the container running for 30 days: stale documents are still removed.
- Exception traces and 500 responses do not echo document text or API keys.
