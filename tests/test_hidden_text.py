"""Hidden-text detection: PDF white/tiny/off-page text and DOCX hidden runs (red-team finding, roadmap v0.2 #5)."""

from __future__ import annotations

import io

from claimtrace.core.models import Commitment, Passage
from claimtrace.extraction import analyze_document
from claimtrace.ingestion import IngestOptions, ingest_bytes
from claimtrace.integrations.llm import FakeProvider
from claimtrace.verification import answer_question

PARTIES = 'This Agreement is made between Acme Ltd (the "Supplier") and Bolt plc (the "Customer").'


def _pdf() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(50, 800, PARTIES)
    c.drawString(50, 780, "2. Delivery")
    c.drawString(50, 760, "2.1 The Supplier shall deliver the goods by 1 June 2026.")
    c.setFillColorRGB(0.98, 0.98, 0.98)
    c.drawString(50, 740, "2.2 The Customer shall pay a bonus of GBP 50,000 on signature.")
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 1)
    c.drawString(50, 720, "2.3 The Customer shall waive all claims for late delivery.")
    c.setFont("Helvetica", 12)
    c.drawString(50, 2000, "2.4 The Customer shall pay all of the Supplier's legal costs.")
    c.drawString(50, 700, "2.5 The Supplier shall provide a delivery note with each shipment.")
    c.save()
    return buf.getvalue()


def _docx() -> bytes:
    import docx
    from docx.oxml.ns import qn
    from docx.oxml.parser import OxmlElement

    d = docx.Document()
    d.add_paragraph(PARTIES)
    d.add_paragraph("3.1 The Supplier shall keep all spare parts in stock.")
    p = d.add_paragraph("3.2 The Supplier shall reply within 5 days. ")
    run = p.add_run("The Customer shall pay a fee of GBP 99,000 for each reply.")
    vanish = OxmlElement("w:vanish")
    run._r.get_or_add_rPr().append(vanish)
    assert run._r.rPr.find(qn("w:vanish")) is not None
    d.add_paragraph("3.3 The Customer shall notify the Supplier of any defect.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _flagged(passages: list[Passage]) -> dict[str, str]:
    return {p.section_number or str(p.ordinal): p.hidden_text for p in passages if p.hidden_text}


def test_pdf_white_tiny_and_off_page_text_is_flagged(store):
    doc = ingest_bytes(store, "a.pdf", _pdf(), IngestOptions(sandbox=False))
    flagged = _flagged(store.passages(doc.id))
    assert set(flagged) == {"2.2", "2.3", "2.4"}, flagged
    assert "white" in flagged["2.2"] and "tiny" in flagged["2.3"] and "off the page" in flagged["2.4"]
    assert any(w.startswith("HIDDEN:") for w in doc.warnings)


def test_pdf_hidden_detection_survives_the_sandbox(store):
    doc = ingest_bytes(store, "a.pdf", _pdf(), IngestOptions(sandbox=True))
    assert set(_flagged(store.passages(doc.id))) == {"2.2", "2.3", "2.4"}


def test_docx_hidden_run_is_flagged(store):
    doc = ingest_bytes(store, "a.docx", _docx(), IngestOptions(sandbox=False))
    flagged = _flagged(store.passages(doc.id))
    assert set(flagged) == {"3.2"}, flagged
    assert "hidden" in flagged["3.2"]
    assert any(w.startswith("HIDDEN:") for w in doc.warnings)


def test_commitments_from_hidden_text_need_review_with_caveat(store):
    doc = ingest_bytes(store, "a.pdf", _pdf(), IngestOptions(sandbox=False, doc_type="contract"))
    analyze_document(store, doc.id)
    cs = {c.section_number: c for c in store.objects(Commitment, doc.id)}
    for sec in ("2.2", "2.3", "2.4"):
        c = cs[sec]
        assert c.needs_review and any("hidden" in r.lower() for r in c.review_reasons)
        assert any("hidden" in cv.lower() for cv in c.caveats)
    assert not cs["2.1"].needs_review and not any("hidden" in cv.lower() for cv in cs["2.1"].caveats)


def test_hidden_passages_are_never_sent_to_a_model(store):
    doc = ingest_bytes(store, "a.pdf", _pdf(), IngestOptions(sandbox=False, doc_type="contract"))
    fake = FakeProvider(lambda s, u: {"commitments": [], "status": "not_addressed", "answer": "", "quotes": []})
    analyze_document(store, doc.id, fake)
    answer_question(store, "Does the Customer pay a bonus on signature?", [doc.id], provider=fake)
    sent = "\n".join(u for _, u in fake.calls)
    assert fake.calls and "deliver the goods" in sent
    for hidden in ("bonus of GBP 50,000", "waive all claims", "legal costs"):
        assert hidden not in sent
