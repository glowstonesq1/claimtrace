"""Apply amendment instructions across stored documents (recomputed after every analysis or delete).

Each instruction's target is looked up in the amended (base) document first. A target that does not
exist there (a clause number, heading, schedule or insertion anchor), or modify wording that does not
occur in the target clause, is never applied: the instruction and any replacement commitments are
flagged for human review instead.
"""

from __future__ import annotations

import hashlib
import re

from claimtrace.core.models import (
    AmendmentInstruction,
    Commitment,
    Confidence,
    Document,
    DocumentEffect,
    Edge,
    EdgeType,
    Passage,
    cap_confidence,
    derive_status,
)
from claimtrace.core.store import Store
from claimtrace.core.text import squash

from .amendments import number_tolerant_pattern

_AMEND_CAVEAT = ("Replaced by ", "Deleted by ", "Changed by ", "Renumbered as ")
_UNRESOLVED = "Amendment target not found: "


def section_matches(section: str | None, target: str) -> bool:
    """`4.1(a)`, `4.1.2` and `4.1` are all inside clause `4.1`; `Schedule 2/1` is inside `Schedule 2`."""
    return bool(section) and (section == target or section.startswith((target + ".", target + "(", target + "/")))  # type: ignore[union-attr]


def _title_section(title: str, passages: list[Passage], doc_title: str) -> tuple[str | None, str | None]:
    """The clause whose heading is exactly `title` (normalised, case-insensitive), or (None, reason).

    There is deliberately no partial match: "Term" must never resolve to "Termination". A heading that
    matches nothing, or matches more than one separate clause, is left for human review.
    """
    want = squash(title)
    hits = [p for p in passages if p.section_title and squash(p.section_title) == want]
    nums = [p.section_number for p in hits if p.section_number]
    if not nums:
        return None, f"no clause headed exactly '{title}' was found in '{doc_title}'"
    top = min(nums, key=len)
    if not all(section_matches(n, top) for n in nums):
        found = ", ".join(sorted({n for n in nums if not any(section_matches(n, m) and n != m for m in nums)}))
        return None, f"more than one clause is headed '{title}' in '{doc_title}' ({found})"
    return top, None


def resolve_target(
    ins: AmendmentInstruction, base: Document, passages: list[Passage], aliases: dict[str, str]
) -> tuple[str | None, str | None]:
    """Return (section in the base document, None) or (None, reason it could not be found)."""
    if ins.action == "restate":
        return "*", None

    def exists(sec: str) -> bool:
        return any(section_matches(p.section_number, sec) for p in passages)

    if ins.action == "insert":
        if ins.anchor_section:
            anchor = aliases.get(ins.anchor_section, ins.anchor_section)
            if not exists(anchor):
                return None, (f"the new text is to go {ins.position or 'after'} clause {ins.anchor_section}, which does not "
                              f"exist in '{base.title}'")
        return ins.target_section, None
    target = ins.target_section
    if target.startswith("title:"):
        title = target[len("title:") :]
        return _title_section(title, passages, base.title)
    sec = aliases.get(target, target)
    if not exists(sec):
        return None, f"clause {target} does not exist in '{base.title}'"
    return sec, None


def restated_counterpart(old: Commitment, restated: list[Commitment]) -> Commitment | None:
    """The commitment in a restated document that carries `old` forward (same clause, or same words)."""
    same_text = next((c for c in restated if squash(c.text) == squash(old.text)), None)
    if same_text:
        return same_text
    if old.section_number:
        return next((c for c in restated if c.section_number == old.section_number), None)
    return None


def _old_words(ins: AmendmentInstruction) -> str | None:
    if ins.old_text:
        return ins.old_text
    m = re.search(
        r"(?:reference\s+to|words?|figure|number|amount)\s+[\"“]?(?P<old>[^\"”]{1,80}?)[\"”]?\s+"
        r"(?:in\s+(?:clause|section)\s+[\d.()a-z]+\s+)?(?:is|are|shall\s+be)",
        ins.provenance.span.quote,
        re.I,
    )
    return m.group("old").strip() if m else None


def apply_amendments(store: Store) -> int:
    """Return the number of base commitments whose document_effect is not in_force."""
    docs = {d.id: d for d in store.list_documents()}
    store.delete_objects_with_prefix("cmt_d_")
    store.delete_edges_of_type(EdgeType.supersedes.value)
    store.delete_edges_of_type(EdgeType.amends.value)
    cms = {d: store.objects(Commitment, d) for d in docs}
    dirty: dict[str, Commitment] = {}
    for clist in cms.values():
        for c in clist:
            stale = [cv for cv in c.caveats if cv.startswith(_AMEND_CAVEAT)]
            stale_review = [r for r in c.review_reasons if r.startswith(_UNRESOLVED)]
            if c.document_effect != DocumentEffect.in_force or stale or stale_review:
                c.document_effect = DocumentEffect.in_force
                c.caveats = [cv for cv in c.caveats if not cv.startswith(_AMEND_CAVEAT)]
                if stale_review:
                    c.review_reasons = [r for r in c.review_reasons if not r.startswith(_UNRESOLVED)]
                    c.needs_review = bool(c.review_reasons) or c.confidence == Confidence.low
                c.status = derive_status(c)
                dirty[c.id] = c
    amendments = sorted((d for d in docs.values() if d.amends_document_id in docs), key=lambda d: d.uploaded_at)
    holder: dict[tuple[str, str], list[Commitment]] = {}
    aliases: dict[str, dict[str, str]] = {}
    passages: dict[str, list[Passage]] = {}
    edges: list[Edge] = []
    derived: list[Commitment] = []
    changed_ins: list[AmendmentInstruction] = []
    affected = 0
    for amd in amendments:
        base_id = amd.amends_document_id
        assert base_id is not None
        base = docs[base_id]
        if base_id not in passages:
            passages[base_id] = store.passages(base_id)
        alias = aliases.setdefault(base_id, {})
        edges.append(Edge(id=f"edg_am_{amd.id}", src_id=amd.id, dst_id=base_id, type=EdgeType.amends))
        loc_title = amd.title
        pending: dict[str, str] = {}  # consecutive renumberings take effect together
        for ins in store.objects(AmendmentInstruction, amd.id):
            if ins.action != "renumber" and pending:
                alias.update(pending)
                pending.clear()
            before = (ins.resolved_section, ins.needs_review, list(ins.review_reasons))
            ins.resolved_section, ins.needs_review, ins.review_reasons = None, False, []
            loc = f"{loc_title} §{ins.provenance.span.section or '?'}"
            new = [c for c in cms[amd.id] if c.amends_section == ins.target_section]
            sec, reason = resolve_target(ins, base, passages[base_id], alias)
            if sec is None:
                _flag(ins, new, f"{_UNRESOLVED}{reason}; the instruction was not applied. Check it against "
                                f"the document it amends.", dirty)
            else:
                ins.resolved_section = sec
                if ins.target_section.startswith("title:"):
                    for n in new:
                        if n.section_number == ins.target_section:
                            n.section_number = sec
                            dirty[n.id] = n
                affected += _apply_one(ins, sec, base_id, amd, cms, holder, pending, new, loc, dirty, derived, edges)
            if (ins.resolved_section, ins.needs_review, ins.review_reasons) != before:
                changed_ins.append(ins)
        alias.update(pending)
    for c in dirty.values():
        store.update_object(c)
    for i in changed_ins:
        store.update_object(i)
    if derived:
        store.add_objects(derived)
    store.add_edges(edges)
    return affected


def _flag(ins: AmendmentInstruction, new: list[Commitment], reason: str, dirty: dict[str, Commitment]) -> None:
    ins.needs_review = True
    ins.review_reasons.append(reason)
    for n in new:
        if reason not in n.review_reasons:
            n.review_reasons.append(reason)
        n.needs_review = True
        dirty[n.id] = n


def _mark(old: Commitment, effect: DocumentEffect, caveat: str, dirty: dict[str, Commitment]) -> None:
    old.document_effect = effect
    old.caveats = [cv for cv in old.caveats if not cv.startswith(("Replaced by ", "Deleted by ", "Changed by "))]
    old.caveats.append(caveat)
    old.status = derive_status(old)
    dirty[old.id] = old


def _supersedes(new: Commitment, old: Commitment, ins: AmendmentInstruction) -> Edge:
    return Edge(id=f"edg_sup_{new.id}_{old.id}"[:60], src_id=new.id, dst_id=old.id, type=EdgeType.supersedes,
                provenance=ins.provenance)


def _apply_one(
    ins: AmendmentInstruction,
    sec: str,
    base_id: str,
    amd: Document,
    cms: dict[str, list[Commitment]],
    holder: dict[tuple[str, str], list[Commitment]],
    renumbering: dict[str, str],
    new: list[Commitment],
    loc: str,
    dirty: dict[str, Commitment],
    derived: list[Commitment],
    edges: list[Edge],
) -> int:
    affected = 0
    if ins.action == "restate":
        restated = [c for c in cms[amd.id] if not c.amends_section]
        for old in cms[base_id]:
            if old.amends_section:
                continue
            twin = restated_counterpart(old, restated)
            if twin is not None:
                _mark(old, DocumentEffect.replaced, f"Replaced by the restated '{amd.title}' "
                                                    f"§{twin.section_number or '?'}.", dirty)
                edges.append(_supersedes(twin, old, ins))
            else:
                _mark(old, DocumentEffect.deleted, f"Deleted by {loc}: not carried into the restated document.", dirty)
            affected += 1
        return affected
    if ins.action == "renumber":
        if ins.renumber_to:
            renumbering[ins.renumber_to] = sec
            for old in cms[base_id]:
                if section_matches(old.section_number, sec) and not old.amends_section:
                    old.caveats = [cv for cv in old.caveats if not cv.startswith("Renumbered as ")]
                    old.caveats.append(f"Renumbered as clause {ins.renumber_to} by {loc}.")
                    dirty[old.id] = old
        return 0
    key = (base_id, sec)
    current = holder.get(key)
    if current is None:
        current = [c for c in cms[base_id] if section_matches(c.section_number, sec) and not c.amends_section]
    if ins.action == "insert":
        holder[key] = new  # an insertion never changes existing clauses
        return 0
    if ins.action == "modify":
        words = _old_words(ins)
        rx = re.compile(number_tolerant_pattern(words), re.I) if words else None
        hits = [old for old in current if rx is not None and rx.search(old.text)]
        if not hits:
            _flag(ins, new, f"{_UNRESOLVED}the words '{words or '?'}' were not found in clause {ins.target_section}; "
                            "the instruction was not applied.", dirty)
            return 0
        assert rx is not None and ins.new_text is not None
        replacement = ins.new_text
        for old in hits:
            d = old.model_copy(deep=True)
            d.id = "cmt_d_" + hashlib.sha256(f"{ins.id}:{old.id}".encode()).hexdigest()[:12]
            d.document_id = amd.id
            d.text = re.sub(r"\s{2,}", " ", rx.sub(lambda _m: replacement, old.text)).replace(" .", ".")
            d.amends_section = ins.target_section
            d.provenance = ins.provenance.model_copy(deep=True)
            d.confidence = cap_confidence(d.confidence, Confidence.medium)
            d.provenance.confidence = d.confidence
            d.caveats = [
                f"Wording derived by applying {loc} to the original clause; the quote shows "
                "the amending instruction, not this exact sentence."
            ]
            d.document_effect = DocumentEffect.in_force
            d.status = derive_status(d)
            derived.append(d)
            new.append(d)
        current = hits
    for old in current:
        effect = DocumentEffect.deleted if ins.action == "delete" else DocumentEffect.replaced
        verb = "Deleted by " if ins.action == "delete" else "Replaced by "
        _mark(old, effect, f"{verb}{loc}" + (f': "{ins.new_text[:160]}"' if ins.new_text else "."), dirty)
        affected += 1
        for n in new:
            edges.append(_supersedes(n, old, ins))
    holder[key] = new
    return affected
