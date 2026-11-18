# Non-technical end-user advocate
## Top 3 concerns
- Install burden (§11 "Docker Compose", §10): an ops manager at a 40-person company cannot install Docker, edit a `.env`, or know what `CLAIMTRACE_RETENTION_DAYS` is. The spec has no non-developer install path, so the persona in §2 row 1 never reaches J1.
- Trust calibration (§5 `Confidence`, J2): "confidence: high" beside a quote will read as "this is correct." It only means rule-derived and quote found. Nothing says it does not cover amendments the user never uploaded. A missed obligation (the §1 failure) will look complete.
- Vocabulary leaks (§5 enums, J2 "graph path", J4 "contradicted", "needs_human_review", "partially_supported", "not_addressed"): §7 says "no jargon" but the spec's own journeys show `Vendor —made_by→ C-12 —requires→ Deadline`. `ReviewStatus` words (resolved, needs_evidence) do not map to anything the user does.
## Top 3 recommendations
- Ship a single-click desktop app or hosted-by-IT bundle as the v0.1 install path. Docker is the developer path. Risk: the target user never sees the product.
- Replace "high/medium/low confidence" in the UI with action wording: "Found in text, check page 3" vs "Unsure, please read". Never show "high" without "only covers uploaded documents". I disagree with a bare Confidence label because it invites over-trust; instead state what was and was not checked.
- Hide graph path by default; show "Where this comes from: MSA > §4.2 > amended by Amendment 1 §2". Map verdicts to plain words: "Same", "Changed", "Not mentioned", "Can't tell, please read".
## Must-have v0.1 requirements
- First 5 minutes: drag a PDF, see the deadline list with quotes within one screen, no settings page, no model choice. A bundled sample contract to try.
- A "documents you have not uploaded" notice on every answer and on the Deadlines view.
- Scanned-PDF detection must be loud, in plain words ("this file is a picture; nothing was read"), because silent empty results look like "no obligations".
- A review flow of three buttons (Looks right / Wrong / Not sure) and an "I handled this" action tied to a real task, such as "Paid", "Notice sent".
- Export of a deadline list that opens in Excel (CSV), since ICS is deferred to v0.2 (§11).
## Defer (and why)
- Graph tab and edge types (§7): vocabulary cost exceeds value for this persona; keep as an advanced view.
- LLM provider setup in the first-run flow: people give up at "enter an API key". Default must work offline.
- Fine-grained commitment types (consequence, service_level): users think "must do / may do / must not do".
## Failure modes to test
- User hands the tool a 3-line scanned PDF, gets "0 commitments", concludes the contract has none.
- User sees "Stated in document, high" for an obligation superseded by an amendment they did not upload and misses the deadline.
- Recipient of a printed report ignores the "not legal advice" footer and forwards findings as a legal position.
- User gives up when the first analysis takes minutes with no progress message (ARIA live region exists but copy unspecified).
- Reviewer marks everything "resolved" to clear the queue; check the report still shows unreviewed counts.
