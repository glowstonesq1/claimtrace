"""Rules baseline extractor: offline, deterministic, explainable.

It is the eval anchor and the zero-setup default (design-review D5/D22). It favours
flagging uncertainty over guessing: no party → low confidence + review; vague or
ambiguous timing → review; qualifiers nearby → caveat.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from dataclasses import dataclass, field

from claimtrace.core.models import (
    EVIDENCE_TYPES,
    AmendmentInstruction,
    Claim,
    Commitment,
    CommitmentType,
    Confidence,
    Definition,
    DocType,
    Document,
    Edge,
    EdgeType,
    Modality,
    Party,
    Passage,
    Provenance,
    Span,
    cap_confidence,
    derive_status,
)
from claimtrace.core.text import find_quote, looks_like_injection, sentences_with_offsets

from . import patterns as P
from .amendments import parse_instructions

EXTRACTOR_VERSION = "rules-0.1.0"

_REMEDY = re.compile(
    r"\b(?:service\s+credits?|liquidated\s+damages|terminat\w*|refund|compensat\w*|penalt\w*|"
    r"interest|rebate|withhold|suspend|damages|indemnif\w*|credit)\b",
    re.I,
)
_SLA = re.compile(
    r"\b(?:availab\w*|uptime|response\s+time|resolution\s+time|resolve|respond|accuracy|latency|"
    r"service\s+levels?)\b",
    re.I,
)
_CONDITIONAL_START = re.compile(r"^\s*(?:if|where|in\s+the\s+event|should|upon|following)\b", re.I)
_CLAUSE_SUBJECT = re.compile(r"^(?:the\s+)?(?:clauses?|sections?|paragraphs?|this\s+clause|this\s+section)\b", re.I)
_LIST_ITEM = re.compile(r"^\s*(?:\([a-z0-9]{1,4}\)|[a-z0-9]{1,3}\))\s+")
_BOILERPLATE = re.compile(r"\bfictional\s+document\b|\bfor\s+claimtrace\s+examples\b", re.I)
_PRONOUN_SUBJECT = re.compile(r"^(?:it|they|he|she|this|that|which|who|such\s+party)$", re.I)


@dataclass
class ExtractionResult:
    commitments: list[Commitment] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    parties: list[Party] = field(default_factory=list)
    definitions: list[Definition] = field(default_factory=list)
    instructions: list[AmendmentInstruction] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def objects(self) -> list:
        return [*self.parties, *self.definitions, *self.commitments, *self.claims, *self.instructions]


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def make_span(doc: Document, p: Passage, start: int, end: int) -> Span:
    """Span from passage-relative offsets."""
    return Span(
        document_id=doc.id,
        passage_id=p.id,
        char_start=p.char_start + start,
        char_end=p.char_start + end,
        quote=p.text[start:end],
        page=p.page,
        section=p.section_number,
        document_title=doc.title,
        document_version=doc.version_label,
    )


def make_prov(
    doc: Document,
    span: Span,
    confidence: Confidence,
    method: str = "rules",
    model: str | None = None,
    host: str | None = None,
    prompt_version: str | None = None,
) -> Provenance:
    return Provenance(
        source_document_id=doc.id,
        document_version=doc.version_label,
        span=span,
        extraction_method=method,
        extractor_version=EXTRACTOR_VERSION,
        model=model,
        endpoint_host=host,
        prompt_version=prompt_version,
        confidence=confidence,
    )


def agreement_date(passages: list[Passage]) -> dt.date | None:
    for p in passages[:6]:
        m = re.search(r"\b(?:dated|made\s+on|entered\s+into\s+on|effective\s+(?:as\s+of|from)|as\s+of)\s+(.{0,40})", p.text, re.I)
        if m:
            found = P.find_dates(m.group(1))
            if found and found[0].date:
                return found[0].date
    return None


class PartyResolver:
    def __init__(self, parties: list[Party]) -> None:
        self.by_key: dict[str, str] = {}
        for p in parties:
            alias = p.alias or p.name
            self.by_key[alias.lower()] = alias
            self.by_key[p.name.lower().rstrip(".")] = alias
        self.aliases = sorted({p.alias or p.name for p in parties})

    def resolve(self, subject: str) -> tuple[str | None, bool]:
        """Return (party label, is_known). Unknown-but-plausible roles return (label, False)."""
        s = re.sub(r"^(?:the|each|any|all|its|their|a|an)\s+", "", subject.strip(" ,;:\"'"), flags=re.I).strip()
        low = subject.strip().lower()
        for k, v in P.COLLECTIVE.items():
            if low.endswith(k):
                return v, True
        if not s:
            return None, False
        if s.lower() in self.by_key:
            return self.by_key[s.lower()], True
        for key, alias in self.by_key.items():
            if re.search(rf"\b{re.escape(key)}\b", s, re.I):
                return alias, True
        last = s.split()[-1]
        if last.lower() in P.ROLE_WORDS or s.lower() in P.ROLE_WORDS:
            return s if s[0].isupper() else s.title(), False
        if s[0].isupper() and P.COMPANY_SUFFIX.search(s):
            return s, False
        return None, False

    def other_party_in(self, text: str, exclude: str | None) -> str | None:
        for alias in self.aliases:
            if alias != exclude and re.search(rf"\b{re.escape(alias)}\b", text):
                return alias
        return None


def _subject_before(text_before: str) -> str:
    seg = re.split(r",|;|:|\bthat\b|\bthen\b|\band\b(?=\s+(?:the|each|either|[A-Z]))", text_before)[-1]
    seg = _LIST_ITEM.sub("", seg)
    seg = re.sub(r"^\s*\d+(?:\.\d+)*\.?\s+", "", seg)
    return seg.strip()


def _commitment_type(modality: Modality, sentence: str, subject: str, action: str) -> CommitmentType:
    sentence = re.sub(r"^\s*(?:\d+(?:\.\d+)*\.?|\([a-z0-9]{1,4}\))\s+", "", sentence)
    if _CLAUSE_SUBJECT.match(subject) or re.search(r"\b(?:does|shall)\s+not\s+apply\b", sentence, re.I):
        return CommitmentType.condition
    if modality == Modality.must_not:
        return CommitmentType.prohibition
    conditional = _CONDITIONAL_START.match(sentence) is not None
    if conditional and _REMEDY.search(action):
        return CommitmentType.consequence
    if modality == Modality.may:
        return CommitmentType.entitlement
    if P.percents(sentence) and _SLA.search(sentence):
        return CommitmentType.service_level
    if re.search(r"\b(?:is|are)\s+conditional\s+(?:up)?on|condition\s+precedent\b", sentence, re.I):
        return CommitmentType.condition
    return CommitmentType.obligation


def extract_rules(doc: Document, passages: list[Passage]) -> ExtractionResult:
    res = ExtractionResult()
    ref_date = agreement_date(passages)

    # 1. parties and definitions (document-wide, first pass)
    seen_alias: set[str] = set()
    for p in passages:
        for pd in P.find_party_definitions(p.text):
            if pd.alias in seen_alias:
                continue
            seen_alias.add(pd.alias)
            start = max(0, pd.start)
            span = make_span(doc, p, start, pd.end)
            res.parties.append(
                Party(
                    id=_id("pty"),
                    document_id=doc.id,
                    name=pd.name,
                    alias=pd.alias,
                    provenance=make_prov(doc, span, Confidence.high),
                )
            )
        for m in re.finditer(
            r"\"(?P<term>[A-Z][\w \-]{1,50})\"\s+(?:shall\s+)?means?\s+(?P<body>[^\n]+?)(?:\.(?:\s|$)|$)", p.text
        ):
            span = make_span(doc, p, m.start(), m.end())
            res.definitions.append(
                Definition(
                    id=_id("def"),
                    document_id=doc.id,
                    term=m.group("term"),
                    definition_text=m.group("body").strip(),
                    provenance=make_prov(doc, span, Confidence.high),
                )
            )
    resolver = PartyResolver(res.parties)

    # 2. amendment instructions (their quoted replacement text is extracted as amendment commitments)
    instruction_passages: set[str] = set()
    if doc.doc_type == DocType.amendment or doc.amends_document_id:
        for p in passages:
            for ins in parse_instructions(p.text):
                span = make_span(doc, p, ins.start, ins.end)
                res.instructions.append(
                    AmendmentInstruction(
                        id=_id("ins"),
                        document_id=doc.id,
                        target_section=ins.target,
                        action=ins.action,
                        new_text=ins.new_text,
                        provenance=make_prov(doc, span, Confidence.high),
                    )
                )
                instruction_passages.add(p.id)
                if ins.new_text and ins.new_start is not None:
                    for c in _commitments_in(doc, p, resolver, ref_date, ins.new_start, ins.new_end):
                        c.amends_section = ins.target
                        c.section_number = ins.target
                        c.status = derive_status(c)
                        res.commitments.append(c)

    # 3. commitments and claims
    lead_in: tuple[str, str] | None = None  # (subject, modal phrase) from "The Supplier shall:"
    for p in passages:
        if p.id in instruction_passages or _BOILERPLATE.search(p.text):
            continue
        text = p.text
        if lead_in and _LIST_ITEM.match(text):
            body_start = _LIST_ITEM.match(text).end()  # type: ignore[union-attr]
            res.commitments.extend(_commitments_in(doc, p, resolver, ref_date, body_start, len(text), lead_in))
            continue
        lead_in = None
        found = _commitments_in(doc, p, resolver, ref_date, 0, len(text))
        res.commitments.extend(found)
        stripped = text.rstrip()
        if stripped.endswith(":"):
            modals = list(P.MODAL_RE.finditer(stripped))
            m = modals[-1] if modals else None
            if m is not None:
                lead_in = (_subject_before(stripped[: m.start()]), m.group("modal"))
                # the lead-in itself is not a commitment
                res.commitments = [c for c in res.commitments if c.provenance.span.passage_id != p.id]
        if doc.doc_type in EVIDENCE_TYPES:
            res.claims.extend(_claims_in(doc, p))

    # 4. edges: made_by, owed_to, requires, conditioned_on, references
    party_ids = {(pt.alias or pt.name): pt.id for pt in res.parties}
    for c in res.commitments:
        prov = c.provenance
        if c.obliging_party and c.obliging_party in party_ids:
            res.edges.append(
                Edge(
                    id=_id("edg"),
                    src_id=c.id,
                    dst_id=party_ids[c.obliging_party],
                    type=EdgeType.made_by,
                    document_id=doc.id,
                    provenance=prov,
                )
            )
        if c.beneficiary_party and c.beneficiary_party in party_ids:
            res.edges.append(
                Edge(
                    id=_id("edg"),
                    src_id=c.id,
                    dst_id=party_ids[c.beneficiary_party],
                    type=EdgeType.owed_to,
                    document_id=doc.id,
                    provenance=prov,
                )
            )
        if c.deadline and c.deadline.kind != "none":
            res.edges.append(
                Edge(
                    id=_id("edg"),
                    src_id=c.id,
                    dst_id=f"deadline:{c.deadline.date or c.deadline.raw}",
                    type=EdgeType.requires,
                    document_id=doc.id,
                    provenance=prov,
                )
            )
        for cond in c.conditions:
            res.edges.append(
                Edge(
                    id=_id("edg"),
                    src_id=c.id,
                    dst_id=f"condition:{cond[:80]}",
                    type=EdgeType.conditioned_on,
                    document_id=doc.id,
                    provenance=prov,
                )
            )
    by_section: dict[str, list[Commitment]] = {}
    for c in res.commitments:
        if c.section_number and not c.amends_section:
            by_section.setdefault(c.section_number, []).append(c)
    for c in res.commitments:
        for ref in c.references:
            for target in by_section.get(ref, []):
                if target.id != c.id:
                    # a condition qualifies the clause it is about (its first reference); others are mentions
                    is_subject = c.type == CommitmentType.condition and ref == c.references[0]
                    etype = EdgeType.qualifies if is_subject else EdgeType.references
                    res.edges.append(
                        Edge(
                            id=_id("edg"), src_id=c.id, dst_id=target.id, type=etype, document_id=doc.id, provenance=c.provenance
                        )
                    )
                    if etype == EdgeType.qualifies and target.caveats is not None:
                        target.caveats.append(f'Qualified by §{c.section_number}: "{c.text[:120]}"')
                        target.confidence = cap_confidence(target.confidence, Confidence.medium)
    return res


def _commitments_in(
    doc: Document,
    p: Passage,
    resolver: PartyResolver,
    ref_date: dt.date | None,
    lo: int,
    hi: int,
    lead_in: tuple[str, str] | None = None,
) -> list[Commitment]:
    out: list[Commitment] = []
    region = p.text[lo:hi]
    sents = sentences_with_offsets(region)
    for idx, (s0, s1, sentence) in enumerate(sents):
        abs0, abs1 = lo + s0, lo + s1
        matches = list(P.MODAL_RE.finditer(sentence))
        bare = re.sub(r"^\s*(?:\d+(?:\.\d+)*\.?|\([a-z0-9]{1,4}\))\s+", "", sentence)
        cond = P.CONDITION_SENTENCE_RE.match(bare)
        if cond:
            off = len(sentence) - len(bare)
            matches_info = [(cond.group("subj"), cond.group("modal"), off + cond.start("modal"), off + cond.end("modal"))]
        elif lead_in and not matches:
            subject, modal_phrase = lead_in
            matches_info = [(subject, modal_phrase, 0, 0)]
        else:
            matches_info = []
            last_subject = None
            for m in matches:
                before = sentence[: m.start()]
                subject = _subject_before(before)
                joined = re.search(r"(?:\band|\bor|,)\s*$", before) and last_subject
                if (not subject or joined) and last_subject:
                    subject = last_subject
                # skip "may" used as a month or inside quoted defined terms
                if m.group("modal").lower() == "may" and re.match(r"\s+\d", sentence[m.end() :]):
                    continue
                matches_info.append((subject, m.group("modal"), m.start(), m.end()))
                last_subject = subject
        next_sentence = sents[idx + 1][2] if idx + 1 < len(sents) else ""
        for k, (subject, modal_phrase, m0, m1) in enumerate(matches_info):
            nxt = matches_info[k + 1][2] if k + 1 < len(matches_info) else len(sentence)
            action = sentence[m1:nxt].strip(" ,;.") if m1 else sentence.strip(" ,;.")
            action = re.sub(r"\s+(?:and|or)$", "", action)
            after_modal = sentence[m0:]
            c = _build_commitment(
                doc, p, resolver, ref_date, sentence, abs0, abs1, subject, modal_phrase, action, after_modal, next_sentence
            )
            if c:
                out.append(c)
    return out


def _build_commitment(
    doc: Document,
    p: Passage,
    resolver: PartyResolver,
    ref_date: dt.date | None,
    sentence: str,
    abs0: int,
    abs1: int,
    subject: str,
    modal_phrase: str,
    action: str,
    after_modal: str,
    next_sentence: str,
) -> Commitment | None:
    modality = P.modality_of(modal_phrase)
    reasons: list[str] = []
    caveats: list[str] = []
    is_passive = P.PASSIVE_RE.match(after_modal) is not None
    if P.NON_OBLIGATION_VERBS.match(after_modal) and not _CLAUSE_SUBJECT.match(subject):
        return None
    party, known = resolver.resolve(subject)
    performer = None
    if re.match(r"shall\s+procure\s+that", modal_phrase, re.I):
        performer = _subject_before(action) or action.split(" ")[0]
        performer = re.sub(r"^(?:its|their|the)\s+", "", performer.split(" shall ")[0].split(" will ")[0])[:60]
    ctype = _commitment_type(modality, sentence, subject, action)
    if party is None:
        if ctype == CommitmentType.condition:
            pass
        elif is_passive:
            reasons.append("No party is named (passive voice).")
        elif _PRONOUN_SUBJECT.match(subject.strip()):
            reasons.append(f"The obliged party is only referred to as '{subject.strip()}'.")
        elif modality == Modality.must and modal_phrase.lower() == "will":
            return None  # "will" with a non-party subject is usually a statement, not a promise
        elif ctype == CommitmentType.service_level:
            reasons.append("No party is named for this service level.")
        else:
            return None  # statements like "This Agreement shall continue..." are not commitments
    elif not known:
        reasons.append(f"'{party}' is not a defined party in this document.")
    deadline = P.extract_deadline(sentence, ref_date)
    conditions = P.find_conditions(sentence)
    exceptions = P.find_exceptions(sentence)
    references = P.find_references(sentence)
    beneficiary = resolver.other_party_in(action, party)
    if (
        beneficiary is None
        and party in resolver.aliases
        and len(resolver.aliases) == 2
        and modality in (Modality.must, Modality.reasonable_efforts, Modality.must_not)
    ):
        beneficiary = next(a for a in resolver.aliases if a != party)  # bilateral: owed to the counterparty

    confidence = Confidence.high
    if party is None and ctype != CommitmentType.condition:
        confidence = Confidence.low
    elif not known:
        confidence = Confidence.medium
    if modality == Modality.reasonable_efforts:
        confidence = cap_confidence(confidence, Confidence.medium)
        reasons.append("Effort standard ('reasonable endeavours' or similar) is not precisely defined.")
    if deadline.kind == "vague":
        confidence = cap_confidence(confidence, Confidence.medium)
        reasons.append(f"Timing is vague ('{deadline.raw}').")
    if deadline.ambiguous_format:
        confidence = cap_confidence(confidence, Confidence.low)
        reasons.append(f"Date '{deadline.raw}' could be read as day/month or month/day.")
    if deadline.kind == "relative" and deadline.date is None and deadline.anchor:
        caveats.append(f"Deadline depends on '{deadline.anchor}'; no calendar date was computed.")
    if exceptions:
        confidence = cap_confidence(confidence, Confidence.medium)
        caveats.append("Has exceptions: " + "; ".join(e[:100] for e in exceptions))
    # stage-2 grounding: qualifiers in the following sentence (design-review D4)
    if next_sentence and P.QUALIFIER_RE.search(next_sentence) and not P.MODAL_RE.search(next_sentence[:12]):
        confidence = cap_confidence(confidence, Confidence.medium)
        caveats.append(f'The next sentence may qualify this: "{next_sentence[:140]}"')
    if (
        re.search(r"\b(?:it|they|them|its)\b", action)
        and len(P.find_party_definitions(sentence)) == 0
        and party is not None
        and re.search(r"\b(?:it|they)\s+(?:shall|must|will)\b", sentence, re.I)
    ):
        reasons.append("Contains an unclear pronoun reference.")
        confidence = cap_confidence(confidence, Confidence.medium)
    if ctype == CommitmentType.condition and not references:
        confidence = cap_confidence(confidence, Confidence.medium)

    span_start = abs0 + (len(sentence) - len(sentence.lstrip()))
    span_end = abs1 - (len(sentence) - len(sentence.rstrip()))
    # leading clause numbers are location, not quote
    num = re.match(r"\s*(?:\d+(?:\.\d+)*\.?|\([a-z0-9]{1,4}\))\s+", p.text[span_start:span_end])
    if num:
        span_start += num.end()
    span = make_span(doc, p, span_start, span_end)
    assert find_quote(p.text, span.quote) is not None
    if looks_like_injection(p.text):
        confidence = Confidence.low
        reasons.append("The passage contains instruction-like text aimed at AI tools; read it yourself.")
    c = Commitment(
        id=_id("cmt"),
        document_id=doc.id,
        text=span.quote,
        type=ctype,
        modality=modality,
        obliging_party=party,
        performer_party=performer,
        beneficiary_party=beneficiary,
        action=action[:400],
        deadline=deadline if deadline.kind != "none" else None,
        conditions=conditions,
        exceptions=exceptions,
        references=references,
        section_number=p.section_number,
        confidence=confidence,
        needs_review=bool(reasons) or confidence == Confidence.low,
        review_reasons=reasons,
        caveats=caveats,
        provenance=make_prov(doc, span, confidence),
    )
    c.status = derive_status(c)
    return c


_CLAIM_KIND = [
    (re.compile(r"\b(?:did\s+not\s+test|not\s+tested|no\s+opinion|out\s+of\s+scope|excluded\s+from)\b", re.I), "scope_limit"),
    (
        re.compile(r"\b(?:implemented|enforced|encrypted|operating\s+effectively|in\s+place|configured|maintained)\b", re.I),
        "control",
    ),
    (re.compile(r"\d+(?:\.\d+)?\s?%|\b(?:measured|availability|uptime)\b", re.I), "measurement"),
    (re.compile(r"\b(?:delivered|issued|received|completed|signed|paid|submitted|notified)\b.*\d{4}", re.I), "event"),
]


def _claims_in(doc: Document, p: Passage) -> list[Claim]:
    out = []
    if len(p.text) < 25 or re.match(r"^\d+(?:\.\d+)*\.?\s+\w+(?:\s+\w+){0,3}$", p.text):
        return out
    if len(p.text) < 100 and not p.text.rstrip().endswith((".", "%", ")", "!", "?")):
        return out  # headings and titles are not claims
    for s0, _s1, sentence in sentences_with_offsets(p.text):
        st = sentence.strip()
        if len(st) < 20 or _BOILERPLATE.search(st):
            continue
        kind = next((k for rx, k in _CLAIM_KIND if rx.search(st)), "statement")
        lead = len(sentence) - len(sentence.lstrip())
        start, end = s0 + lead, s0 + lead + len(st)
        num = re.match(r"(?:\d+(?:\.\d+)*\.?)\s+", p.text[start:end])
        if num:
            start += num.end()
        span = make_span(doc, p, start, end)
        out.append(
            Claim(
                id=_id("clm"),
                document_id=doc.id,
                text=span.quote,
                claim_type=kind,
                section_number=p.section_number,
                confidence=Confidence.high,
                needs_review=False,
                provenance=make_prov(doc, span, Confidence.high),
            )
        )
    return out
