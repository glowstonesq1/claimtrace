"""Apply amendment instructions across stored documents (recomputed after every analysis or delete)."""

from __future__ import annotations

import hashlib
import re

from claimtrace.core.models import (
    AmendmentInstruction,
    Commitment,
    Confidence,
    DocumentEffect,
    Edge,
    EdgeType,
    cap_confidence,
    derive_status,
)
from claimtrace.core.store import Store

_AMEND_CAVEAT = ("Replaced by ", "Deleted by ", "Changed by ")


def _matches_section(c: Commitment, section: str) -> bool:
    return bool(c.section_number) and (c.section_number == section or c.section_number.startswith(section + "("))


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
            if c.document_effect != DocumentEffect.in_force or any(cv.startswith(_AMEND_CAVEAT) for cv in c.caveats):
                c.document_effect = DocumentEffect.in_force
                c.caveats = [cv for cv in c.caveats if not cv.startswith(_AMEND_CAVEAT)]
                c.status = derive_status(c)
                dirty[c.id] = c
    amendments = sorted((d for d in docs.values() if d.amends_document_id in docs), key=lambda d: d.uploaded_at)
    holder: dict[tuple[str, str], list[Commitment]] = {}
    edges: list[Edge] = []
    derived: list[Commitment] = []
    affected = 0
    for amd in amendments:
        base = amd.amends_document_id
        assert base is not None
        edges.append(Edge(id=f"edg_am_{amd.id}", src_id=amd.id, dst_id=base, type=EdgeType.amends))
        for ins in store.objects(AmendmentInstruction, amd.id):
            key = (base, ins.target_section)
            current = holder.get(key)
            if current is None:
                current = [c for c in cms[base] if _matches_section(c, ins.target_section) and not c.amends_section]
            new = [c for c in cms[amd.id] if c.amends_section == ins.target_section]
            loc = f"{amd.title} §{ins.provenance.span.section or '?'}"
            if ins.action == "modify" and ins.new_text:
                old_text = _old_from_instruction(ins)
                for old in current:
                    if old_text and re.search(re.escape(old_text), old.text, re.I):
                        d = old.model_copy(deep=True)
                        d.id = "cmt_d_" + hashlib.sha256(f"{ins.id}:{old.id}".encode()).hexdigest()[:12]
                        d.document_id = amd.id
                        d.text = re.sub(re.escape(old_text), ins.new_text, old.text, flags=re.I)
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
            if ins.action in ("replace", "modify", "delete", "insert"):
                if ins.action == "insert" and not current:
                    holder[key] = new
                    continue
                for old in current:
                    old.document_effect = DocumentEffect.deleted if ins.action == "delete" else DocumentEffect.replaced
                    verb = "Deleted by " if ins.action == "delete" else "Replaced by "
                    old.caveats = [cv for cv in old.caveats if not cv.startswith(_AMEND_CAVEAT)]
                    old.caveats.append(f"{verb}{loc}" + (f': "{ins.new_text[:160]}"' if ins.new_text else "."))
                    old.status = derive_status(old)
                    dirty[old.id] = old
                    affected += 1
                    for n in new:
                        edges.append(
                            Edge(
                                id=f"edg_sup_{n.id}_{old.id}"[:60],
                                src_id=n.id,
                                dst_id=old.id,
                                type=EdgeType.supersedes,
                                provenance=ins.provenance,
                            )
                        )
                holder[key] = new
    for c in dirty.values():
        store.update_object(c)
    if derived:
        store.add_objects(derived)
    store.add_edges(edges)
    return affected


def _old_from_instruction(ins: AmendmentInstruction) -> str | None:
    m = re.search(
        r"(?:reference\s+to|words?|figure|number|amount)\s+[\"“]?(?P<old>[^\"”]{1,80}?)[\"”]?\s+"
        r"(?:in\s+(?:clause|section)\s+[\d.()a-z]+\s+)?(?:is|are|shall\s+be)",
        ins.provenance.span.quote,
        re.I,
    )
    return m.group("old").strip() if m else None
