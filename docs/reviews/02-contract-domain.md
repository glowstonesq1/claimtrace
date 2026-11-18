# Contract-analysis domain reviewer
## Top 3 concerns
- Commitment model (§5) is flat: `obliging_party`, `deadline{raw,date?,kind}`, `conditions[]`, `exceptions[]` cannot express "Party A shall procure that Party B..." (obligor vs. performer), passive voice ("Notice shall be given" has no party), or defined-term obligors ("the Supplier" as a Party alias). Rules extractor keyed on "shall/must" will miss "will", "agrees to", "undertakes", "is responsible for", "is required to". I disagree that a rules baseline is meaningful recall-wise without a documented modal/verb-pattern inventory; the risk is a baseline that looks fine on synthetic cases the author wrote.
- Status enum conflates axes. `CommitmentStatus` (stated, amended, superseded, open, fulfilled, disputed, unknown) mixes document-derived state (amended/superseded) with lifecycle state (open/fulfilled/disputed). "Amended" is also ambiguous: restate-in-full vs. replace-clause vs. delete vs. add. A clause can be superseded in part only. Risk: wrong "current" date shown in J2/J4.
- No order-of-precedence, notwithstanding, or cross-reference handling. "Notwithstanding clause 4.2", "subject to clause 9", "in the event of conflict the Order Form prevails" decide which of two contradicting commitments governs, yet §4 J4 just says "confirm which date governs". `references` edge exists but nothing resolves "clause 14.3", "Schedule 2", or "Section 3(b)(ii)" to passages.
## Top 3 recommendations
- Split status into `document_effect` (in_force, amended_in_part, replaced, deleted, superseded_by_precedence) and `lifecycle` (open/fulfilled/disputed, human-set only, answering open question 2: yes). Record amendment `mode` (restate/replace/insert/delete) on the `amends` edge with target clause number.
- Extend Commitment: `performer_party` separate from `obliging_party`, `modality` (absolute, best-efforts, reasonable-endeavours, discretionary "may"), `condition_kind` (precedent vs. subsequent vs. trigger), `exception_kind`, `overrides[]`/`subject_to[]` edges, and `deadline.kind` incl. relative ("within 30 days of Effective Date"), recurring, business-day with calendar jurisdiction, and "promptly/as soon as practicable" (non-computable).
- Add a Definitions-first pass: resolve defined terms (Effective Date, Business Day, Affiliate) before deadline computation; store unresolved relative deadlines as raw with `date=null` plus the anchor reference, never guess.
## Must-have v0.1 requirements
- Entitlement vs. obligation distinction ("may", "is entitled to") and prohibition ("shall not") must not be classed as obligations; test negation scoping.
- Relative deadlines keep anchor event and offset; absolute `date` only when anchor is resolved.
- Exceptions detected for "except as", "save that", "unless", "provided that", "subject to"; commitment flagged needs_review when an exception exists but its span is unparsed.
- Clause-number cross-reference resolver (numbering styles 1.1, (a), (i), Schedule/Annex) producing `references` edges; unresolved refs flagged.
- Amendment application shows original vs. amended text side by side, never silently overwrites the original commitment.
## Defer (and why)
- Full precedence/governing-law logic across more than two documents: needs the pair model proven first; v0.1 should only surface clause detected and show both quotes.
- Jurisdiction-specific business-day/holiday calendars: store the term and flag; compute in v0.2.
- Aggregate "who owes what" netting across a whole contract suite: depends on reliable party resolution.
## Failure modes to test
- "Supplier shall procure that its subcontractors deliver..." attributed to subcontractors or to nobody.
- Amendment says "Section 4.2 is deleted and replaced with the following", old commitment still reported as stated.
- "Notwithstanding anything in clause 4.2, Vendor may deliver by 15 May" produces a false `contradicted` finding instead of an override.
- "Within 10 Business Days after the Effective Date" computed from upload date or calendar days.
- Numbered sub-list ("(a) ... (b) ...") under a lead-in "The Vendor shall:" extracted as separate commitments with no obliger.
