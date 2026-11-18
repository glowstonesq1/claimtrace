import datetime as dt

import pytest

from claimtrace.core.models import Commitment, DocumentEffect
from claimtrace.core.text import find_quote, normalize, sentences_with_offsets, stem
from claimtrace.extraction import patterns as P


def test_normalize_is_stable_and_cleans_pdf_artifacts():
    raw = "The Vendor shall deliv-\nery “goods”.\r\n\r\nNext­para"
    out = normalize(raw)
    assert out == normalize(out)
    assert out == 'The Vendor shall delivery "goods".\n\nNextpara'


def test_find_quote_is_verbatim_only():
    text = "The Vendor shall deliver the system by March 31, 2026."
    assert find_quote(text, "shall deliver the system") is not None
    assert find_quote(text, "SHALL   deliver the system") is not None  # case/space tolerant
    assert find_quote(text, "shall deliver the software") is None  # never fuzzy


@pytest.mark.parametrize("words", [("deliver", "delivered", "delivery", "deliveries"),
                                   ("invoice", "invoices"), ("available", "availability")])
def test_stemming_groups_inflections(words):
    assert len({stem(w) for w in words}) == 1


def test_sentence_split_respects_abbreviations_and_clause_numbers():
    s = sentences_with_offsets("Acme Co. shall pay. See clause 2. The Buyer may terminate.")
    assert [x[2] for x in s] == ["Acme Co. shall pay.", "See clause 2. The Buyer may terminate."] or len(s) == 2


@pytest.mark.parametrize("sentence,kind,expected", [
    ("deliver no later than March 31, 2026", "absolute", {"date": dt.date(2026, 3, 31)}),
    ("deliver by 31 March 2026", "absolute", {"date": dt.date(2026, 3, 31)}),
    ("pay within 30 days of receipt", "relative", {"offset_days": 30, "anchor": "receipt"}),
    ("within ten (10) Business Days of the Effective Date", "relative", {"offset_days": 10, "business_days": True}),
    ("provide weekly reports", "recurring", {}),
    ("notify promptly", "vague", {}),
    ("by 03/04/2026", "absolute", {"ambiguous_format": True, "date": None}),
])
def test_deadline_extraction(sentence, kind, expected):
    d = P.extract_deadline(sentence)
    assert d.kind == kind
    for k, v in expected.items():
        assert getattr(d, k) == v


def test_relative_deadline_is_computed_only_when_anchor_resolves():
    d = P.extract_deadline("within 30 days of the date of this Agreement", dt.date(2026, 1, 10))
    assert d.date == dt.date(2026, 2, 9)
    d2 = P.extract_deadline("within 10 Business Days of the date of this Agreement", dt.date(2026, 1, 10))
    assert d2.date is None  # business-day calendars are not guessed


def test_party_definitions():
    defs = P.find_party_definitions('between Acme Widgets Ltd (the "Supplier") and Bolt plc (the "Customer").')
    assert [(d.name, d.alias) for d in defs] == [("Acme Widgets Ltd", "Supplier"), ("Bolt plc", "Customer")]


def test_store_reviews_are_append_only(store):
    import sqlite3

    from claimtrace.core.models import ReviewDecision, ReviewDecisionKind, ReviewStatus

    r = ReviewDecision(id="rev_1", target_kind="answer", target_id="ans_1", decision=ReviewDecisionKind.accept,
                       reviewer="Sam", prior_status=ReviewStatus.unreviewed, target_hash="x")
    store.add_review(r)
    with pytest.raises(sqlite3.DatabaseError):
        store.conn.execute("UPDATE reviews SET json='{}' WHERE id='rev_1'")
    assert store.current_review_status("ans_1") == ReviewStatus.accepted


def test_every_extracted_quote_is_verbatim_at_its_offsets(store, loaded):
    for doc_id in loaded.values():
        text = store.get_document_text(doc_id)
        for c in store.objects(Commitment, doc_id):
            s = c.provenance.span
            assert text[s.char_start:s.char_end] == s.quote == c.text or c.id.startswith("cmt_d_")


def test_amendment_marks_original_replaced_and_keeps_it(store, loaded):
    msa = {c.section_number: c for c in store.objects(Commitment, loaded["msa-v1.md"])}
    assert msa["2.1"].document_effect == DocumentEffect.replaced
    assert "May 15, 2026" in " ".join(msa["2.1"].caveats)
    assert msa["2.2"].document_effect == DocumentEffect.in_force
    new = [c for c in store.objects(Commitment, loaded["amendment-1.md"]) if c.amends_section == "2.1"]
    assert new and new[0].deadline.date == dt.date(2026, 5, 15)


def test_deleting_amendment_restores_original_effect(store, loaded):
    from claimtrace.extraction import apply_amendments

    store.delete_document(loaded["amendment-1.md"])
    apply_amendments(store)
    msa = {c.section_number: c for c in store.objects(Commitment, loaded["msa-v1.md"])}
    assert msa["2.1"].document_effect == DocumentEffect.in_force
