# Audit and compliance reviewer
## Top 3 concerns
- §1/§4 J5 conflate evidence existence with sufficiency. "Evidence gap" (§8) and `supports`/`evidence_for` edges can only show a passage mentions a control, not that it satisfies it. A "consistent" verdict on an audit report will be read as "control operating effectively". I disagree with the Verdict enum offering `consistent` for control claims; the risk is a workpaper that sounds like an opinion.
- §5 `ReviewDecision` and §6 `DELETE /documents/{id}` (hard delete, §9 retention purge) destroy the trail. Findings, answers and review decisions vanish with the document, and v1.0 defers the audit log (§11). A review trail you can erase, or that has no append-only guarantee, is not a trail. `review_status` on Finding is also mutable in place.
- §6 `analyze` is "idempotent per (checksum, extractor version)", but `Provenance` records `model` and `prompt_version` only, not extractor/parser/normaliser version, segmentation version or config. Text normalisation changes shift `char_start/char_end`, so a finding re-run months later cannot be reproduced or its spans re-resolved.
## Top 3 recommendations
- Replace `consistent` for evidence checks with an explicit two-axis result: `evidence_located` (yes/no, with quote) and `sufficiency` (always `reviewer_judgement_required` until a human sets it). Never auto-assert implemented/effective.
- Make review events append-only: each `ReviewDecision` is a new row with reviewer, UTC timestamp, target content hash and prior status; current status is derived. Deletion writes a tombstone (ids, checksums, timestamps, no text) instead of vanishing.
- Stamp every run (analysis, ask, verify) with a `run_manifest`: document checksums, parser/normaliser/extractor versions, model, prompt hash, config, and a hash of the output. Embed it in every export.
## Must-have v0.1 requirements
- `reviewer` is a required, non-empty field; with no auth, record an explicit "unauthenticated, self-declared" flag so exports do not imply identity.
- Exports (md/json/html) carry: document SHA-256s, run manifest, review trail with timestamps, items still `unreviewed` listed prominently, generation time, tool version, and a content hash of the report.
- Re-verify the stored passage text against the document checksum on report generation; fail loudly on mismatch.
- JSON export must be a stable, schema-versioned format so a workpaper reviewer can diff two runs.
- Print HTML must show page/section locators and full quotes (no truncation) so a reviewer can re-perform.
## Defer (and why)
- Full tamper-evident hash chain or signatures: valuable but v1.0; append-only rows plus manifests give most of the value now.
- Multi-user RBAC and segregation of duties (preparer vs reviewer): needs accounts; just record names now.
- SOC 2 control-mapping templates: risk of shipping wrong mappings; ship wording guardrails first.
## Failure modes to test
- Audit report states "access reviews performed quarterly" and the evidence attached is one dated review: the tool must not mark sufficient.
- Document is deleted after a finding was accepted; the exported report from before must still be verifiable.
- Re-upload with the same checksum after an extractor upgrade: are old findings silently overwritten or versioned?
- Reviewer accepts a finding, then the document is re-analysed and the span shifts; does the acceptance attach to stale text?
- Two reviewers give conflicting decisions on one finding; is the history visible in the export?
