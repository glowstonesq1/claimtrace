"""Cross-document verification. Every finding carries the exact spans it is based on."""

from __future__ import annotations

import uuid

from claimtrace import __version__
from claimtrace.core.models import (
    EVIDENCE_TYPES,
    AmendmentInstruction,
    Claim,
    Commitment,
    CommitmentType,
    DocType,
    Document,
    DocumentEffect,
    Finding,
    Party,
    Severity,
    Span,
    Verdict,
    VerificationRun,
)
from claimtrace.core.store import Store
from claimtrace.core.text import tokens
from claimtrace.extraction import patterns as P
from claimtrace.extraction.rules import EXTRACTOR_VERSION

from .compare import Comparison, compare_values, judge, places, topic_overlap

_MODALS = set(tokens("shall must will may not", keep_stopwords=True))
CHECKABLE = {CommitmentType.obligation, CommitmentType.prohibition, CommitmentType.service_level, CommitmentType.deadline}
_HIGH_TOPICS = tokens(
    "data security encrypt breach personal deliver delivery payment pay fee price liability "
    "availability penetration confidential terminate insurance"
)

ACTIONS = {
    ("amendment", Verdict.contradicted): "Confirm the amended wording governs and update your records. The original "
    "text is kept for reference.",
    ("amendment", Verdict.not_addressed): "No action unless you expected this clause to change.",
    ("evidence", Verdict.consistent): "Evidence text was located. Decide whether it is sufficient (e.g. dated, "
    "covers the full period and scope).",
    ("evidence", Verdict.contradicted): "Raise with the responsible party and request an explanation or remediation evidence.",
    ("evidence", Verdict.partially_supported): "Ask for evidence covering the gap or exception described.",
    ("evidence", Verdict.not_addressed): "Request evidence; absence of evidence here does not show the commitment was missed.",
    ("evidence", Verdict.needs_human_review): "Read both passages and decide; the automatic comparison was not conclusive.",
}
DEFAULT_ACTIONS = {
    Verdict.consistent: "No action needed beyond spot-checking the quotes.",
    Verdict.contradicted: "Decide which document governs (check any order-of-precedence clause) and resolve the "
    "conflict with the other party.",
    Verdict.partially_supported: "Check the uncovered part and request clarification.",
    Verdict.not_addressed: "Check whether the other document should cover this.",
    Verdict.ambiguous: "Read both passages; the wording is unclear.",
    Verdict.needs_human_review: "Read both passages and decide; the automatic comparison was not conclusive.",
}


def _severity(verdict: Verdict, c: Commitment, cmp: Comparison | None, mode: str) -> Severity:
    if verdict == Verdict.consistent:
        return Severity.info
    if verdict == Verdict.not_addressed:
        return Severity.info if mode == "amendment" else Severity.low
    fields = set(cmp.fields) if cmp else set()
    topical = bool(set(tokens(c.text)) & set(_HIGH_TOPICS))
    if verdict == Verdict.contradicted and (
        fields & {"date", "amount", "percent", "duration", "place"}
        or topical
        or c.type in (CommitmentType.prohibition, CommitmentType.service_level)
    ):
        return Severity.high
    return Severity.medium


def effective_commitments(store: Store, base_id: str) -> list[Commitment]:
    """Commitments that currently govern for a base document, including amendment replacements."""
    out = [c for c in store.objects(Commitment, base_id) if c.document_effect == DocumentEffect.in_force]
    for d in store.list_documents():
        if d.amends_document_id == base_id:
            out += [c for c in store.objects(Commitment, d.id) if c.document_effect == DocumentEffect.in_force]
    return out


def _mode(base: Document, other: Document) -> tuple[str, Document, Document]:
    if base.doc_type in EVIDENCE_TYPES and other.doc_type not in EVIDENCE_TYPES:
        base, other = other, base
    if other.amends_document_id == base.id or (other.doc_type == DocType.amendment and base.doc_type != DocType.amendment):
        return "amendment", base, other
    if base.amends_document_id == other.id:
        return "amendment", other, base
    if other.doc_type in EVIDENCE_TYPES:
        return "evidence", base, other
    if base.title.strip().lower() == other.title.strip().lower():
        return "version", base, other
    return "general", base, other


def _finding(
    run_id: str,
    verdict: Verdict,
    c: Commitment,
    explanation: str,
    severity: Severity,
    mode: str,
    supporting: list[Span] | None = None,
    conflicting: list[Span] | None = None,
    sufficiency: str | None = None,
) -> Finding:
    return Finding(
        id="fnd_" + uuid.uuid4().hex[:12],
        run_id=run_id,
        verdict=verdict,
        subject_id=c.id,
        subject_text=c.text,
        subject_span=c.provenance.span,
        supporting=supporting or [],
        conflicting=conflicting or [],
        explanation=explanation,
        severity=severity,
        recommended_action=ACTIONS.get((mode, verdict), DEFAULT_ACTIONS[verdict]),
        sufficiency=sufficiency,
    )


def verify_documents(store: Store, base_id: str, other_id: str) -> VerificationRun:
    base, other = store.get_document(base_id), store.get_document(other_id)
    mode, base, other = _mode(base, other)
    run_id = "ver_" + uuid.uuid4().hex[:12]
    if mode == "amendment":
        findings = _amendment(store, run_id, base, other)
    elif mode == "evidence":
        findings = _evidence(store, run_id, base, other)
    else:
        findings = _pairwise(store, run_id, base, other, mode)
    summary: dict[str, int] = {v.value: 0 for v in Verdict}
    for f in findings:
        summary[f.verdict.value] += 1
    run = VerificationRun(
        id=run_id,
        base_document_id=base.id,
        other_document_id=other.id,
        mode=mode,
        findings=findings,
        summary=summary,
        run_manifest={
            "claimtrace_version": __version__,
            "extractor_version": EXTRACTOR_VERSION,
            "method": "rules",
            "documents": {
                d.id: {"title": d.title, "version": d.version_label, "checksum": d.checksum_sha256, "text_sha256": d.text_sha256}
                for d in (base, other)
            },
        },
    )
    store.save_verification(run)
    return run


def _amendment(store: Store, run_id: str, base: Document, amd: Document) -> list[Finding]:
    base_cs = store.objects(Commitment, base.id)
    amd_cs = store.objects(Commitment, amd.id)
    touched: set[str] = set()
    out: list[Finding] = []
    for ins in store.objects(AmendmentInstruction, amd.id):
        olds = [
            c
            for c in base_cs
            if c.section_number
            and (c.section_number == ins.target_section or c.section_number.startswith(ins.target_section + "("))
        ]
        news = [c for c in amd_cs if c.amends_section == ins.target_section]
        new_spans = [n.provenance.span for n in news] or [ins.provenance.span]
        for old in olds:
            touched.add(old.id)
            if ins.action == "delete":
                out.append(
                    _finding(
                        run_id,
                        Verdict.contradicted,
                        old,
                        f"Clause {ins.target_section} is deleted by the amendment.",
                        Severity.high,
                        "amendment",
                        conflicting=[ins.provenance.span],
                    )
                )
                continue
            cmp = next((r for n in news if (r := compare_values(old, n.text, evidence_mode=False))), None)
            detail = cmp.explanation if cmp and cmp.verdict == Verdict.contradicted else "The wording was replaced."
            out.append(
                _finding(
                    run_id,
                    Verdict.contradicted,
                    old,
                    f"Changed by the amendment (§{ins.target_section}). {detail}",
                    _severity(Verdict.contradicted, old, cmp, "amendment"),
                    "amendment",
                    conflicting=new_spans,
                )
            )
        if ins.action == "insert" and not olds:
            for n in news:
                out.append(
                    _finding(
                        run_id,
                        Verdict.not_addressed,
                        n,
                        f"New clause {ins.target_section} added by the amendment; the original document does not address it.",
                        Severity.medium,
                        "amendment",
                        supporting=[n.provenance.span],
                    )
                )
    # amendment commitments that change a base clause by reference ("reduce the fee in clause 3.1 to ...")
    for n in amd_cs:
        if n.amends_section:
            continue
        for ref in n.references:
            for old in (c for c in base_cs if c.section_number == ref and c.id not in touched):
                cmp = compare_values(old, n.text, evidence_mode=False)
                if cmp and cmp.verdict == Verdict.contradicted:
                    touched.add(old.id)
                    out.append(
                        _finding(
                            run_id,
                            Verdict.contradicted,
                            old,
                            f"Changed by the amendment (§{n.section_number}). {cmp.explanation}",
                            _severity(Verdict.contradicted, old, cmp, "amendment"),
                            "amendment",
                            conflicting=[n.provenance.span],
                        )
                    )
    for old in base_cs:
        if old.id not in touched:
            out.append(
                _finding(
                    run_id,
                    Verdict.not_addressed,
                    old,
                    "Not changed by this amendment; it remains in force as written.",
                    Severity.info,
                    "amendment",
                )
            )
    return out


def _party_tokens(store: Store, *doc_ids: str) -> set[str]:
    out: set[str] = set()
    for d in doc_ids:
        for p in store.objects(Party, d):
            out |= set(tokens(f"{p.name} {p.alias or ''}"))
    return out


def _evidence(store: Store, run_id: str, base: Document, ev: Document) -> list[Finding]:
    claims = store.objects(Claim, ev.id)
    items: list[tuple[str, Span]] = [(c.text, c.provenance.span) for c in claims]
    if not items:
        items = [
            (
                p.text,
                Span(
                    document_id=ev.id,
                    passage_id=p.id,
                    char_start=p.char_start,
                    char_end=p.char_end,
                    quote=p.text,
                    page=p.page,
                    section=p.section_number,
                    document_title=ev.title,
                    document_version=ev.version_label,
                ),
            )
            for p in store.passages(ev.id)
        ]
    generic = _party_tokens(store, base.id, ev.id)
    out: list[Finding] = []
    for c in effective_commitments(store, base.id):
        if c.type not in CHECKABLE:
            continue
        scored = []
        for text, span in items:
            ov, shared = topic_overlap(c.action or c.text, text, generic)
            ov2, shared2 = topic_overlap(c.text, text, generic)
            ov, shared = max((ov, shared), (ov2, shared2), key=lambda x: (len(x[1]), x[0]))
            common = (set(tokens(c.text)) & set(tokens(text))) - generic - _MODALS
            place_link = bool(places(c.text) and places(text) and common)
            typed_link = bool(shared) and any(f(c.text) and f(text) for f in (P.percents, P.amounts, P.durations))
            if (len(shared) >= 2 and ov >= 0.2) or len(shared) >= 3 or place_link or typed_link:
                scored.append((ov, text, span))
        scored.sort(key=lambda x: -x[0])
        if not scored:
            out.append(
                _finding(
                    run_id,
                    Verdict.not_addressed,
                    c,
                    "No matching text found in the evidence document. This does not mean the commitment was missed.",
                    Severity.low,
                    "evidence",
                )
            )
            continue
        top = [s for s in scored if s[0] >= scored[0][0] * 0.6][:3]
        cmp = judge(c, [t for _, t, _ in top], evidence_mode=True)
        spans = [sp for _, _, sp in top]
        supporting = spans if cmp.verdict in (Verdict.consistent, Verdict.partially_supported) else []
        conflicting = (
            spans if cmp.verdict in (Verdict.contradicted, Verdict.partially_supported, Verdict.needs_human_review) else []
        )
        if cmp.verdict == Verdict.partially_supported:
            from .compare import NEGATIVE

            supporting = [sp for _, t, sp in top if not NEGATIVE.search(t)]
            conflicting = [sp for _, t, sp in top if NEGATIVE.search(t)]
        suff = "reviewer_judgement_required" if cmp.verdict in (Verdict.consistent, Verdict.partially_supported) else None
        out.append(
            _finding(
                run_id,
                cmp.verdict,
                c,
                cmp.explanation,
                _severity(cmp.verdict, c, cmp, "evidence"),
                "evidence",
                supporting=supporting,
                conflicting=[] if cmp.verdict == Verdict.not_addressed else conflicting,
                sufficiency=suff,
            )
        )
    return out


def _sentence_items(store: Store, doc: Document, exclude_quotes: set[str]) -> list[tuple[str, Span]]:
    """Every sentence of a document as a comparison candidate (schedules and policies often state terms
    without modal verbs, so commitments alone miss them)."""
    from claimtrace.core.text import sentences_with_offsets, squash

    out = []
    for p in store.passages(doc.id):
        for a, _b, sent in sentences_with_offsets(p.text):
            st = sent.strip()
            if len(st) < 12 or squash(st) in exclude_quotes:
                continue
            lead = len(sent) - len(sent.lstrip())
            start = a + lead
            out.append((st, Span(document_id=doc.id, passage_id=p.id, char_start=p.char_start + start,
                                 char_end=p.char_start + start + len(st), quote=p.text[start:start + len(st)],
                                 page=p.page, section=p.section_number, document_title=doc.title,
                                 document_version=doc.version_label)))
    return out


def _pairwise(store: Store, run_id: str, base: Document, other: Document, mode: str) -> list[Finding]:
    from claimtrace.core.text import squash

    base_cs = effective_commitments(store, base.id)
    other_cs = effective_commitments(store, other.id)
    generic = _party_tokens(store, base.id, other.id)
    items: list[tuple[str, Span, Commitment | None]] = [(o.text, o.provenance.span, o) for o in other_cs]
    covered = {squash(o.text) for o in other_cs}
    items += [(t, sp, None) for t, sp in _sentence_items(store, other, covered)
              if not any(squash(t) in q or q in squash(t) for q in covered)]
    used: set[str] = set()
    out: list[Finding] = []
    for c in base_cs:
        scored = []
        for text, span, o in items:
            ov, shared = topic_overlap(c.text, text, generic)
            same_sec = mode == "version" and o is not None and c.section_number and c.section_number == o.section_number
            common = (set(tokens(c.text)) & set(tokens(text))) - generic - _MODALS
            place_link = bool(places(c.text) and places(text) and common)
            typed_link = bool(shared) and any(f(c.text) and f(text) for f in (P.percents, P.amounts, P.durations))
            date_link = bool(shared) and bool(c.deadline and c.deadline.date) and bool(P.find_dates(text))
            if (same_sec and ov >= 0.3) or (len(shared) >= 2 and ov >= 0.25) or len(shared) >= 3 or place_link \
                    or typed_link or date_link:
                scored.append((ov + (0.5 if same_sec else 0), text, span, o))
        if not scored:
            out.append(_finding(run_id, Verdict.not_addressed, c, f"No corresponding text found in '{other.title}'.",
                                Severity.low, mode))
            continue
        scored.sort(key=lambda x: -x[0])
        top = [x for x in scored if x[0] >= scored[0][0] * 0.7][:3]
        for _, _, _, o in top:
            if o is not None:
                used.add(o.id)
        cmp = judge(c, [t for _, t, _, _ in top], evidence_mode=False)
        if cmp.verdict == Verdict.consistent and scored[0][0] < 0.34 and "topic" in cmp.fields:
            cmp = Comparison(Verdict.needs_human_review, "Possibly related text, but the wording differs too much to "
                                                         "confirm automatically.", ["topic"])
        spans = [sp for _, _, sp, _ in top]
        out.append(_finding(run_id, cmp.verdict, c, cmp.explanation, _severity(cmp.verdict, c, cmp, mode), mode,
                            supporting=spans if cmp.verdict == Verdict.consistent else [],
                            conflicting=spans if cmp.verdict != Verdict.consistent else []))
    for o in other_cs:
        if o.id not in used:
            out.append(_finding(run_id, Verdict.not_addressed, o, f"Appears only in '{other.title}'; "
                                f"'{base.title}' does not address it.", Severity.low, mode))
    return out
