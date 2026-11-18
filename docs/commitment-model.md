# ClaimTrace commitment model

Describes commit 1899c3c.

How the rules extractor (`packages/extraction/rules.py`, `patterns.py`) turns sentences
into commitments, how amendments change them (`amendments.py`, `apply.py`), and the exact
confidence rules (D5). The optional LLM extractor (`llm.py`) is covered where it differs.
Differences from `docs/design-review.md` and `docs/product-spec.md` are noted. This is a
review aid, not legal advice.

## 1. Commitment fields

| Field | Meaning |
|---|---|
| id, document_id | `cmt_` + 12 hex (`cmt_d_` for wording derived by a "modify" amendment). |
| text | The exact quote (equals `provenance.span.quote`). A leading clause number is excluded. |
| type | `CommitmentType`, see section 2.2. |
| modality | must, must_not, may, reasonable_efforts. |
| obliging_party | Party label: a defined alias ("Vendor"), a collective ("Either party"), an undefined role or company name, or `None`. |
| performer_party | Intended for "procure that" drafting. Never set by the rules extractor at this commit (section 2.6). |
| beneficiary_party | Another defined party named in the action, else the counterparty in a two-party document for must, must_not and reasonable_efforts. `None` for may. |
| action | Text after the modal verb up to the next modal in the sentence (max 400 chars). |
| deadline | `Deadline` or `None` (section 3). |
| conditions, exceptions, references | Section 2.5. |
| section_number | The passage's section. For amendment replacement text, the **target** section (e.g. "2.1"), not the amendment's own clause number; the span's `section` keeps the amendment clause ("1.1"). |
| document_effect | in_force, replaced, deleted (section 4). |
| lifecycle | open, fulfilled, disputed, unknown. Set only by a human through a review request. |
| amends_section | Set when the commitment is replacement or inserted text from an amendment. |
| status | Derived (section 4). |
| confidence, needs_review, review_reasons, caveats | Section 6. |
| provenance | Span, method, versions, model fields. |

## 2. How the rules classify a sentence

Passages are split into sentences (`sentences_with_offsets`; no split after common
abbreviations or after a bare clause number such as "2."). Each modal match in a sentence
can produce one commitment. Passages matching the sample-document boilerplate ("fictional
document", "for ClaimTrace examples") are skipped.

### 2.1 Modal verb inventory (`patterns._MODAL_PHRASES`)

The combined regex tries the groups in this order at each position:

| Modality | Phrases |
|---|---|
| must_not | shall not, must not, will not, may not, cannot, can not, is/are not permitted to, is/are prohibited from, agrees not to, undertakes not to, shall refrain from, shall in no event, will never, shall never |
| reasonable_efforts | shall/will use [all] [commercially] reasonable/best/its best/its reasonable endeavours/efforts/endeavors; shall/will endeavour/endeavor |
| may | is/are entitled to, shall/will be entitled to, may, has/have the right to, reserves the right to, is/are permitted to |
| must | shall, must, will, agrees to, agree to, undertakes to, undertake to, is/are responsible for, shall be responsible for, is/are required to, is obliged to, is obligated to, covenants to, commits to, warrants that, shall procure that |

Because "shall" appears before "shall be responsible for" and "shall procure that" in the
must group, those two phrases are captured as "shall". The modality is the same (must).
"may" followed by a digit ("May 15") is skipped.

A separate pattern, `CONDITION_SENTENCE_RE`, matches sentences such as "Clause 6.1 does not
apply where ...", "Section 4 is subject to ...", "Clause 3 applies only ...". The subject is
the clause reference and the "modal" is the verb phrase (modality defaults to must).

### 2.2 Type

`_commitment_type`, first match wins:

1. Subject is "clause/section/paragraph ..." or the sentence says "does/shall not apply" →
   `condition`.
2. Modality must_not → `prohibition`.
3. Sentence starts with if, where, in the event, should, upon or following **and** the action
   names a remedy (service credit, liquidated damages, terminate, refund, compensation,
   penalty, interest, rebate, withhold, suspend, damages, indemnify, credit) → `consequence`.
4. Modality may → `entitlement`.
5. Sentence has a percentage and a service-level word (availability, uptime, response or
   resolution time, resolve, respond, accuracy, latency, service level) → `service_level`.
6. "is/are conditional (up)on" or "condition precedent" → `condition`.
7. Otherwise → `obligation`.

`deadline` is never assigned by the rules; the LLM extractor may return it.

### 2.3 Subject and party resolution

The subject is the text before the modal, cut at the last comma, semicolon, colon, "that",
"then", or "and" before a capitalised word, with list markers and clause numbers removed.
If a second modal follows "and", "or" or a comma ("must keep ... and must not disclose"), it
reuses the previous subject.

`PartyResolver.resolve` returns (label, known):

- ends with "either party", "each party", "both parties", "the parties", "neither party" →
  that collective, known;
- matches a defined party alias or name (after dropping the, each, any, all, its, their, a,
  an) → the alias, known;
- last word is a role word (customer, vendor, supplier, licensee, landlord, ... about 60
  words) → the subject, **not known**;
- capitalised with a company suffix (Ltd, Inc, LLC, GmbH, plc, ...) → the subject, not known;
- otherwise `None`.

Parties are defined by `Name (the "Alias")`, kept when the name has a company suffix or the
alias is a role word.

### 2.4 When a modal does not produce a commitment

- The words after the modal are a non-obligation verb (be governed, construed, interpreted,
  deemed, continue, remain, survive, apply, commence, take effect, prevail, mean, include,
  be read), unless the subject is a clause reference.
- No party resolved, the sentence is not a condition, not passive and the subject is not a
  pronoun, and either the modal is "will" or the type is not service_level. Example: "This
  Agreement shall continue ..." is dropped.

Kept with a review reason instead: passive voice (`shall/must/will [not] be <verb>ed` or an
irregular participle such as paid, made, given, provided), a pronoun subject (it, they, he,
she, this, that, which, who, such party), and a service level with no party.

### 2.5 Lead-in lists, conditions, exceptions, references

**Lead-in lists.** A passage that ends with ":" and contains a modal ("The Supplier
shall:") sets a lead-in of (subject, modal). Following passages that start with a list
marker ("(a)", "a)", "1)") use that subject and modal when they contain no modal of their
own. The lead-in passage itself yields no commitment. The lead-in ends at the first passage
that is not a list item. Section numbers of list items become "1.3(a)".

**Conditions** (`find_conditions`): clauses starting with if, where, provided/providing that,
on condition that, in the event that/of, once, conditional (up)on; and upon, following, after
only at the start of the sentence. "subject to" is treated as an exception.

**Exceptions** (`find_exceptions`): except, excluding, unless, save that, save as, save for,
other than, notwithstanding, without [someone's] [prior] [written] consent/approval/agreement,
plus every "subject to ...".

**References** (`find_references`): numbers after clause, section, paragraph, schedule,
annex, appendix, article, e.g. "6.1", "2(a)", or a single capital letter for schedules.
References become `references` edges to commitments in the same document; a condition's
first reference becomes a `qualifies` edge (section 6.2).

### 2.6 Procure-that performer

`_build_commitment` sets `performer_party` only when the captured modal phrase is "shall
procure that". The regex captures "shall" first (section 2.1), so this branch is not reached
and `performer_party` is always `None` from the rules. "The Supplier shall procure that its
subcontractors comply ..." is extracted as an obligation of the Supplier with no performer.
D3 asks for this field; it exists in the model but is not populated.

## 3. Deadlines

`extract_deadline(sentence, reference_date)` checks in order:

| Kind | Rule | Date computed? |
|---|---|---|
| absolute | A date (`March 31, 2026`, `31 March 2026`, `2026-03-31`, `31/03/2026`) preceded by no later than, not later than, on or before, by, before, until, prior to, on, not after, in any event by. | Yes, from the text. For `a/b/yyyy`, only if one part is over 12 or both are equal; otherwise `date=None` and `ambiguous_format=True`. |
| relative | `<n> <unit>` (n as digits or words up to twenty, thirty, forty(-five), fifty, sixty, ninety, hundred, a/an) with within, later than, notice, after, before, following, at least, not more than or period of nearby; optional business/working/banking/calendar; optional anchor after of, after, from, following, before, prior to. | Only if the anchor mentions "date of this agreement/contract", "effective date" or "commencement date", the document has a reference date ("dated", "made on", "entered into on", "effective as of/from", "as of" in the first six passages), the unit is days or weeks, and it is not business days. Otherwise `date=None`. `offset_days` is set for days and weeks only. |
| recurring | weekly, monthly, quarterly, annually, daily, each/every month, once a year, ... | No. |
| vague | promptly, as soon as (reasonably) practicable/possible, without undue delay, timely, forthwith, in due course, within a reasonable time, immediately, from time to time ... | No. |
| absolute (bare) | Any date without a deadline preposition. | Yes, as raw context. |
| none | Nothing found; stored as `deadline: null`. | |

Business-day calendars are not implemented (v0.2 backlog), so business-day offsets never
produce a date.

## 4. document_effect, lifecycle and derived status (D2)

| Axis | Values | Who sets it |
|---|---|---|
| document_effect | in_force, replaced, deleted | `apply_amendments`, recomputed for every document after each analysis, upload, patch and delete. |
| lifecycle | open, fulfilled, disputed, unknown | A person, via `POST /commitments/{id}/review` with `lifecycle`. |
| status | stated, amended, superseded, open, fulfilled, disputed | `derive_status`: superseded if replaced or deleted; else fulfilled or disputed from lifecycle; else amended if `amends_section`; else open from lifecycle; else stated. |

D2 lists document_effect values in_force, amended, replaced, deleted, superseded. The code
has three; "amended" and "superseded" appear only as derived `status` values.

## 5. Amendments

Instructions are parsed only in documents with `doc_type=amendment` or an
`amends_document_id`. Replacement text must be inside straight or curly double quotes,
5 to 2000 characters, within one passage.

| Action | Supported drafting (case-insensitive; "clause" may be section, paragraph or article; "of the Agreement" optional; "hereby" optional) |
|---|---|
| replace | `Clause X is/shall be deleted [in its entirety] and replaced with/by: "..."`; `Clause X is amended to read / so as to read / as follows: "..."`; `Clause X is replaced [in its entirety] with/by "..."`; `Clause X is restated to read / as follows: "..."` (optionally "the following [new] clause N") |
| insert | `The following / A new [clause] is added/inserted [to/into the X] as [a new] clause N: "..."`; `[A new] clause N is added/inserted ...: "..."` |
| delete | `Clause X is deleted / removed / struck [in its entirety] [and shall have no further effect]` ending the sentence |
| modify | `In clause X, the reference to / word(s) / figure / number / amount "old" is/are replaced/substituted/amended with/by/to "new".`; `The reference to / word(s) / figure "old" in clause X is replaced with "new".` |

Applying them (`apply_amendments`):

1. Reset every commitment to `in_force` and remove earlier amendment caveats; delete all
   `cmt_d_` commitments and all `amends`/`supersedes` edges.
2. For each amendment whose base is stored, oldest upload first, add an `amends` edge, then
   for each instruction find the current base commitments for the target section (exact
   match, or "X(" sub-items; a previous amendment's replacement if one exists).
3. replace, delete, and insert onto an existing section mark them `replaced` or `deleted`,
   add the caveat `Replaced by <title> §<instruction section>: "<new text>"` or `Deleted by
   <title> §<section>.`, and add `supersedes` edges from each new commitment.
4. modify: when the old words occur in a base commitment, create a derived copy with the
   words substituted, confidence capped at medium, and the caveat "Wording derived by
   applying ... the quote shows the amending instruction, not this exact sentence."
5. insert with no existing section: the new commitments simply stand.

Known unsupported drafting:

- Replacement text without quotes, or spanning more than one paragraph.
- Changes by narrative or reference ("the Vendor shall reduce the fixed fee in clause 3.1
  to GBP 110,000"). This is extracted as an ordinary obligation; the base clause stays
  `in_force`. Verify (amendment mode) reports it; Ask does not.
- Amendments to definitions, schedules or annexes; renumbering; "clause X is amended by
  deleting ... and inserting ..."; sub-clause targets at deeper levels (1.3.1 is not matched
  by 1.3).
- Linking by title requires the base to be uploaded first and the `amends:` front matter to
  equal its title. Otherwise the link must be set via `amends_document_id`.

## 6. Confidence and review (exact rules)

Confidence is categorical and rule-derived. Rules commitments start at `high`.

### 6.1 Rules applied while building a commitment (in this order)

| # | Condition | Effect | Review reason / caveat |
|---|---|---|---|
| 1 | No party resolved and type is not condition | set low | reason from 2.4 (passive, pronoun, or service level) |
| 1b | Party not known (role word or company not defined; also a condition with no party) | set medium | "'X' is not a defined party in this document." (only when a label exists) |
| 2 | modality reasonable_efforts | cap medium | "Effort standard ('reasonable endeavours' or similar) is not precisely defined." |
| 3 | deadline vague | cap medium | "Timing is vague ('<raw>')." |
| 4 | date format ambiguous | cap low | "Date '<raw>' could be read as day/month or month/day." |
| 5 | relative deadline with anchor and no date | none | caveat "Deadline depends on '<anchor>'; no calendar date was computed." |
| 6 | any exception found | cap medium | caveat "Has exceptions: ..." |
| 7 | next sentence matches a qualifier (except, unless, subject to, notwithstanding, provided that, save that/as, however, does/shall not apply, other than, excluding, in no event) and has no modal in its first 12 chars | cap medium | caveat "The next sentence may qualify this: ..." (D4 stage 2) |
| 8 | action contains it/they/them/its, a party was resolved, the sentence defines no party, and has "it/they shall/must/will" | cap medium | "Contains an unclear pronoun reference." |
| 9 | type condition with no references | cap medium | none |
| 10 | the passage looks like a prompt injection | set low | "The passage contains instruction-like text aimed at AI tools; read it yourself." |

`needs_review = bool(review_reasons) or confidence == low`. Rules 5, 6, 7 and 9 lower
confidence or add a caveat without flagging review.

### 6.2 Rules applied after building

| Where | Condition | Effect |
|---|---|---|
| `extract_rules` edges | Commitment is the target of a `qualifies` edge | cap medium; caveat `Qualified by §X: "..."`. `provenance.confidence` is not updated, so it can read high while `confidence` is medium. |
| `apply_amendments` | Derived "modify" wording | cap medium (provenance updated). |
| `apply_amendments` | replaced or deleted | confidence unchanged; caveat added. |

D4 lists "not" as a qualifier; the code's qualifier list does not include it.

### 6.3 LLM extractor

Items whose quote matches a rules commitment do not create a new commitment; if the party
agrees, the rules item's `extraction_method` becomes `rules+llm`. Confidence is not raised
(the module docstring says it is). Items found only by the model: medium if the model named
an obliging party, else low; cap low if the deadline is vague or ambiguous; always
`needs_review` with "Found only by the language model; check the quote and party."
Items from passages that look like injections are dropped.

`unknown` is never assigned to a commitment. It is used for answers with no support.

## 7. Worked example: MSA clause 2.1 and Amendment No. 1

Input, `examples/documents/msa-v1.md`, passage section 2.1:

> 2.1 The Vendor shall deliver the Phase 1 System no later than March 31, 2026.

1. Parties: `Halden Freight Co. (the "Customer")` and `Corvane Software Ltd. (the
   "Vendor")` (company suffix). Reference date: "entered into on January 10, 2026".
2. Modal "shall" → must. Subject "The Vendor" → "Vendor", known.
3. Type: no rule before 7 matches → obligation.
4. Deadline: "March 31, 2026" preceded by "no later than" → absolute, date 2026-03-31.
5. Beneficiary: no party in the action; two parties and modality must → "Customer".
6. Confidence: no rule applies → high, `needs_review=false`. Quote excludes "2.1 ".
7. Edges: made_by → Vendor party, owed_to → Customer party, requires →
   `deadline:2026-03-31`.

Input, `examples/documents/amendment-1.md` (front matter `doc_type: amendment`, `amends:
Master Services Agreement`, so `amends_document_id` is the MSA), passage 1.1:

> 1.1 Clause 2.1 of the Agreement is deleted and replaced with: "The Vendor shall deliver
> the Phase 1 System no later than May 15, 2026."

8. `REPLACE_RE` gives instruction (target 2.1, replace, new text). The quoted text is
   extracted as a commitment: obligation, Vendor → Customer, absolute 2026-05-15, high,
   `amends_section="2.1"`, `section_number="2.1"`, span section "1.1", status amended.
9. `apply_amendments`: MSA 2.1 becomes `document_effect=replaced`, status superseded,
   caveat `Replaced by Amendment No. 1 to Master Services Agreement §1.1: "The Vendor shall
   deliver the Phase 1 System no later than May 15, 2026."`. A `supersedes` edge runs from
   the new commitment to the old one; an `amends` edge from the amendment to the MSA.
   Clauses 3.2 and 5.3 are handled the same way; 1.4 inserts clause 5.5.
10. Amendment clause 2.1 ("the Vendor shall reduce the fixed fee in clause 3.1 to GBP
    110,000") is an ordinary obligation with reference 3.1; MSA 3.1 stays in_force.

Both the original and the replacement text are kept (D1).
