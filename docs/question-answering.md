# ClaimTrace question answering and verification

Describes commit 1899c3c.

How `POST /ask` (`packages/verification/ask.py`) and `POST /verify`
(`packages/verification/verify.py`, `compare.py`) produce answers and findings. Retrieval is
in `packages/retrieval/__init__.py`. Differences from the [design decisions](architecture.md#9-design-decisions)
and `docs/product-spec.md` are noted. Answers cover only the uploaded documents and are not
legal advice.

## 1. Answer pipeline

`answer_question(store, question, document_ids=None, provider=None, today=None)`:

1. Truncate the question to 1000 characters (the API also requires 3–1000). Scope is the
   given documents (up to 50) or all documents.
2. Load passages, commitments, claims and edges for the scope.
3. Route by intent (section 2). Each handler returns an `Answer`.
4. Add the scope caveat: "Only covers the documents searched; documents you have not
   uploaded (e.g. later amendments) are not reflected."
5. Re-verify every citation (section 8). Remove any that fail, add the caveat "Some
   citations could not be verified against the stored text and were removed." and set
   `needs_review`.
6. If the status is not `not_addressed` and no remaining citation has role `supports` or
   `conflicts`, replace status, text and confidence with `not_addressed`, the not-found
   sentence, and `unknown`.
7. Write the run manifest (`claimtrace_version`, `composer`, document checksums and
   versions, plus LLM fields if the LLM composer answered) and save the answer.

## 2. Intent routing

Checked in this order on the lower-cased question; the first match wins.

| Intent | Trigger (regex, simplified) | Handler output |
|---|---|---|
| due-soon | "due" or "deadline(s)" … "next N days" | In-force commitments with a computed `deadline.date` between today and today+N, sorted by date. A caveat counts in-force commitments with relative, recurring or vague timing and no date. If none are due: status `not_addressed`, text "No commitment with a calendar date falls between <today> and <horizon>.", confidence medium, undated items cited as `context`. |
| changed | changed/amended/modified/replaced/different … "amendment", or "amendment" … change/amend | Every commitment not in force, with its current version (`"old" → "new"`) or "was deleted", plus amendment commitments with no outgoing `supersedes` edge ("New §X"). Confidence high. Caveat: changes made by reference are found by Verify, not here. |
| evidence-gaps | "no (supporting) evidence", "not (been) evidenced", "unsupported", "lack… evidence" | Runs `verify_documents` for each non-evidence, non-amendment document against each evidence document; lists commitments whose findings are all `not_addressed`. Confidence medium. |
| conflicts | conflict…, inconsisten…, contradict… | Runs `verify_documents` for every document pair; lists `contradicted` findings whose subject shares a content term with the question (all, if the question has no other terms). Status `contradicted`, confidence medium, `needs_review`. |
| list | starts with what/which/list/show and mentions obligations, commitments, duties, entitlements, rights, prohibitions | In-force commitments, filtered by a party named in the question and by type (rights/entitle → entitlement; prohibit/must not/not allowed → prohibition; obligation/duties/must → obligation, service_level, deadline, prohibition). Confidence medium if any item needs review, else high. A caveat counts replaced or deleted items left out. |
| lookup | anything else | Section 3. |

## 3. Lookup: retrieval and coverage

**Terms.** `expand_query` tokenises (lower case, stop words removed, suffix stemming) and
adds tokens from `EXPANSIONS` for each raw word: uk/u.k/britain → united kingdom; us/usa →
united states; eu → european union; mfa/2fa → multi factor authentication; sla → service
level; pentest → penetration test; pay/paid → payment; late → delay; deadline/due → no
later than; uptime → availability; terminate → termination; cancel → terminate; kept,
stored, located → hosted/stored/located; delivery/delivered → deliver; miss/misses → fails;
and a few others. Question words and generic words (`_QWORDS`: what, which, does, agreement,
contract, report, audit, evidence, say, mention, ...) are removed.

**Candidates.** For consequence questions ("what happens", consequence, remedy, penalty,
"if … miss/fail/late/breach/does not"), passages are restricted to those holding a
consequence or condition commitment, if any exist.

**Retrieval.** BM25 (k1=1.4, b=0.75) over passage text, top 6 hits. Dense or hybrid
retrieval is not implemented.

**Weighted coverage.** `term_groups` makes one group per original question word (the word's
token plus its expansions), so expansions widen matching without adding to the denominator.
Each group's weight is the highest IDF of its tokens; a token absent from the index gets
`max IDF + 1`. A hit's coverage = sum of weights of groups it matches / total weight. A
missing rare word ("convenience") costs more than a missing common one.

**Threshold.** A hit is kept if coverage ≥ 0.5 (≥ 1.0 when the question has one group)
and it matched at least `min(2, groups)` tokens. The code comment states 0.5 was chosen on
the core eval set, where no not-found case scored above 0.45.

**Expected answer type.** Unless it is a consequence question, the question is classified
and kept hits must contain that kind of value:

| Question pattern | Type | Passage must contain |
|---|---|---|
| which/what country, city, location, jurisdiction, region; starts with "where" | place | a known place name (`compare.places`) |
| how often, how frequently, how many times | frequency | once, twice, annually, monthly, per year, every …, … |
| how many/much days/weeks/months/hours/years/notice/time, how long, within how, notice period | duration | a duration |
| how much, what fee/amount/price/cost/sum/rate, maximum/minimum amount, what does … pay | amount | an amount or percentage |
| starts with "when", by what date, what date | date | a date or a duration |

If nothing survives, the answer is not found; the top two hits are cited with role
`checked_not_supporting` and the note "Closest passage found; it does not answer the
question."

## 4. Composing a lookup answer

With a provider configured, the LLM composer runs first (section 7). Otherwise, or if it
returns nothing:

1. Take the best hit's passage. Pick the commitment in it sharing the most terms with the
   question; if none, the best sentence (clause number excluded).
2. Status `stated`; confidence high if coverage ≥ 0.75, else medium. Graph path from
   section 6 of `docs/data-model.md`.
3. **Amendment awareness.** Follow `supersedes` edges from a replaced commitment to its
   current version. If they differ: cite the current text as `context`, add the caveat
   `<original location> was replaced by <current location>: "<text>"`, confidence medium.
   If the commitment was deleted: caveat "<location> was deleted by a later amendment.",
   confidence medium. Commitment caveats are copied, except Replaced/Deleted/Qualified ones.
4. **Qualifiers.** Each `qualifies` edge into the commitment adds the qualifying clause as a
   `context` citation, a caveat, and sets confidence medium.
5. **Specifics check.** Dates (including "March 31" without a year), amounts, percentages,
   places and durations named in the question are compared with the original and, if
   replaced, the current text:

| Result | Lead sentence | Effect |
|---|---|---|
| matches original only | "Originally yes, but this was later changed. " | Original stays first; current text appended. |
| matches current only | "Yes, after the amendment. " | Current text cited first as `supports`, original as `context`. |
| matches (yes/no question) | "Yes. " | |
| mismatch | "No. The documents state a different value. " | status `contradicted` |
| no values, or replaced and no conflict | none | If replaced, the current text is shown first: "Currently: … This replaced the original wording in …". |

6. **Cross-document conflict.** For obligation, prohibition and service_level commitments
   (the current version if replaced), each claim from an in-scope evidence document is
   compared when it shares a place, or a percentage plus a topic word, or two topic words.
   The first typed `contradicted` comparison (section 10) is added as a `conflicts` citation
   and caveat, and confidence becomes medium.
7. **Promise-question rule.** If the question asks what was promised (promise, agree,
   commit, require, obligat…, undert…, "contract say", "supposed to", must, shall), the
   conflict stays context and the status is unchanged. Otherwise the status becomes
   `contradicted`, the lead is "The documents disagree. ", and the body adds "However,
   <location> says: ...".
8. If still `stated` and coverage < 0.75, confidence drops one step (medium → low).
9. `needs_review` is true for `contradicted`. Up to three follow-up questions are added.

Example (sample documents): "Did the vendor promise delivery by March 31?" returns status
`stated`, confidence low, text starting "Originally yes, but this was later changed.",
citing MSA §2.1 (supports), Amendment §1.1 (context) and the delivery record (conflicts,
"Done on 22 May 2026, after the deadline of 15 May 2026 (7 days late).").

## 5. The not-found sentence

Exactly:

```
I could not find support for this in the uploaded documents.
```

It is returned by lookup with no qualifying hit, by `changed` or `list` with nothing to
list, when the LLM composer returns `not_addressed`, and by step 6 of section 1. The answer
then has status `not_addressed`, confidence `unknown`, and the caveat "Absence from these
documents does not mean the answer is 'no'." (except via step 6, which keeps the handler's
caveats).

## 6. Statuses produced

| Status | Produced by |
|---|---|
| stated | lookup, list, due-soon, changed, evidence-gaps (with results); LLM composer |
| contradicted | lookup (value mismatch, or evidence conflict on a non-promise question), conflicts; LLM composer |
| not_addressed | not-found paths; due-soon with nothing due; step 6 of section 1; LLM composer |
| needs_human_review | LLM composer only in effect. Evidence-gaps returns it when scope lacks a contract or an evidence document, but with no citations, so step 6 turns it into `not_addressed` with the not-found sentence. |
| implied | LLM composer only. |
| ambiguous | LLM composer only. |

Likewise, conflicts with nothing found ("No conflicting terms were detected ...") and
evidence-gaps with nothing missing are returned with no citations and become the not-found
sentence.

## 7. Optional LLM composer and its fallback

Used only inside lookup, only after hits pass the coverage and answer-type checks, with
the top four passages. For an external endpoint, passages from documents without
`allow_external_llm` are removed; if none remain, the deterministic composer answers. Each
sent document is logged in `egress_log` (purpose `answer`). The passages are wrapped as
untrusted data; the model returns `{status, answer, citations[{passage_id, quote}],
caveats}`.

| Outcome | Result |
|---|---|
| Invalid JSON, schema error, provider error, unknown status | fall back to deterministic composer |
| status `not_addressed` | not-found answer |
| no citation found verbatim (`find_quote`) in its passage | fall back to deterministic composer |
| otherwise | model's status and text, verified citations only, confidence medium, caveat if any were dropped, `needs_review` if any dropped or status is not `stated` |

LLM-composed answers skip steps 3–7 of section 4 (no amendment, qualifier, specifics or
evidence-conflict checks). The global provider setting applies to `/ask`; there is no
per-request switch.

## 8. Citation verification

`verify_citation(store, span)` passes when the stored text at `char_start:char_end` equals
the quote, or `find_quote` finds the quote anywhere in the document (exact, else case- and
whitespace-insensitive; never fuzzy). Reports re-check exact offsets only.

## 9. Verification modes and pairing

`verify_documents(base, other)` infers the mode (`_mode`):

1. If base is an evidence type (audit_report, evidence, report) and other is not, swap.
2. `amendment` if other amends base, or other is an amendment and base is not; or base
   amends other (swapped so the base is first).
3. `evidence` if other is an evidence type.
4. `version` if the titles are equal (case-insensitive).
5. otherwise `general`.

**Amendment mode** (per instruction): base commitments in the target section (or its
"(x)" sub-items).

| Case | Verdict | Severity |
|---|---|---|
| delete | contradicted: "Clause X is deleted by the amendment." | high |
| replace / modify / insert over existing | contradicted: "Changed by the amendment (§X). <typed detail or 'The wording was replaced.'>" | from section 11 |
| insert of a new section | not_addressed on the new commitment | medium |
| amendment commitment referencing a base section whose typed comparison contradicts (e.g. the fee in clause 3.1) | contradicted | from section 11 |
| base commitment untouched | not_addressed: "Not changed by this amendment ..." | info |

Amendment mode never returns `consistent`.

**Evidence mode.** For each in-force base commitment (including amendment replacements) of
type obligation, prohibition, service_level or deadline, candidates are the evidence
document's claims (or its passages if it has none). Party names and generic words are
ignored. A candidate pairs when: ≥ 2 shared topic words and overlap ≥ 0.2; or ≥ 3 shared;
or both mention places and share a word; or they share a topic word and both contain a
percentage, amount or duration. Up to three candidates scoring ≥ 60% of the best are
judged. No candidate → `not_addressed`, severity low.

**Version and general modes.** Base in-force commitments of every type against the other
document's in-force commitments plus its other sentences. Pair when: (version mode only)
same section and overlap ≥ 0.3; ≥ 2 shared and overlap ≥ 0.25; ≥ 3 shared; place link;
typed link; or the commitment has a computed date and the text has a date. Same section
adds 0.5 to the score. Up to three candidates ≥ 70% of the best are judged. A topic-only
`consistent` with best score < 0.34 becomes `needs_human_review`. Unpaired base items →
`not_addressed` (low); unused commitments of the other document → `not_addressed` ("Appears
only in ...").

D24 says to pair by clause number, party, type and lexical overlap. The code uses clause
number only in version mode, removes party names instead of matching them, and filters by
type only in evidence mode.

## 10. Typed comparisons (`compare_values`, `judge`)

`compare_values` checks, returning at the first decisive field:

1. Evidence mode: the other text says it was not examined (did not test, not in scope, no
   opinion, excluded from) → `not_addressed`.
2. Contract modes: modality of the other text's first modal differs → `contradicted`; must
   vs reasonable_efforts → `partially_supported`.
3. Date (only if the commitment has a computed date): evidence mode, latest date after due
   → `contradicted` with days late, else `consistent`; contract modes, different →
   `contradicted`.
4. Percentage: equal → consistent; evidence mode with higher-is-better wording (availability,
   uptime, at least, minimum, ...) compares direction; else different → contradicted.
5. Amount: equal → consistent; evidence mode "at least/minimum" met → consistent; else
   contradicted.
6. Duration (same unit): equal value but anchors overlapping < 0.5 → `needs_human_review`
   ("The clock may start later."); equal → consistent; evidence mode shorter → consistent;
   else contradicted.
7. Place: other places within the commitment's places (EU/EEA expand to member countries)
   → consistent; else contradicted.
8. Nothing comparable → `None`.

`judge` over the candidates: any `contradicted` wins; then `needs_human_review`; then
negative wording (not, failed, missing, however, breach, gap, ...) together with positive
text or an exception word → `partially_supported`; scope-limit `not_addressed` if no
positives; negatives only → `needs_human_review` for prohibitions, else `contradicted`; a
typed `consistent`; otherwise `consistent` with "Matching text was located in the other
document." (evidence) or "The other document states the same commitment." No path returns
`ambiguous`.

## 11. Severity and recommended actions

| Verdict | Severity |
|---|---|
| consistent | info |
| not_addressed | info in amendment mode, low otherwise (amendment inserts: medium) |
| contradicted | high if a date, amount, percent, duration or place field decided it, or the commitment mentions data, security, encrypt, breach, personal, delivery, payment, fee, price, liability, availability, penetration, confidential, terminate or insurance, or it is a prohibition or service level; else medium. Amendment deletes: high. |
| other | medium |

Recommended actions: evidence mode and amendment mode have their own texts (for example
evidence `contradicted`: "Raise with the responsible party and request an explanation or
remediation evidence."; evidence `not_addressed`: "Request evidence; absence of evidence
here does not show the commitment was missed."). Other combinations use defaults (for
example `contradicted`: "Decide which document governs (check any order-of-precedence
clause) and resolve the conflict with the other party.").

## 12. Evidence sufficiency wording (D6)

In evidence mode, `consistent` and `partially_supported` findings carry
`sufficiency="reviewer_judgement_required"`; other verdicts carry `None`. The recommended
action for evidence `consistent` is "Evidence text was located. Decide whether it is
sufficient (e.g. dated, covers the full period and scope)." The web UI shows a "You decide"
badge: "Whether this evidence is sufficient is a judgement for you." Reports list "Whether
evidence is sufficient" under what was not checked.

Differences from D6: there is no separate `evidence_located` field; the UI labels
`consistent` as "Matches", not "Evidence found — you decide if it is enough"; and
`consistent` can come from a typed field (a date on or before the deadline), not only
located text.

Sample result (MSA vs audit report): availability 99.5% vs measured 99.1% → contradicted,
high; data outside the United Kingdom vs Dublin → contradicted, high; MFA → partially
supported with sufficiency wording; breach notice 72 hours from different anchors →
needs_human_review.

## 13. Calendar export (ICS, v0.2)

`GET /documents/{id}/deadlines.ics` and `claimtrace report <id> --format ics` produce an RFC 5545
calendar (`report.deadlines_ics`). Only commitments that are **in force** (the base document's own
and its amendments' replacements) and whose deadline has a **resolved calendar date** become
events; relative deadlines with an unresolved anchor, vague timing and ambiguous `a/b/yyyy` dates
are left out (they stay in the CSV and the register). Each event is an all-day `VEVENT` with a
stable `UID` (`<commitment id>@claimtrace.local`), `SUMMARY` "<party>: <action>", and a
`DESCRIPTION` holding the verbatim quote, the source location, the timing as written, review
flags, caveats and the not-legal-advice note. Text values are escaped (`\\`, `\;`, `\,`, `\n`),
lines end in CRLF and are folded at 75 octets without splitting a UTF-8 character. The file is
built locally and returned as a download (`Content-Disposition: attachment`); nothing is sent or
subscribed to.
