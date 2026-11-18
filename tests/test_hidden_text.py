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


# ---- evasion (code review): fragment splitting, character styles, near-white colours


def _pdf_white_in_pieces(n: int = 5) -> bytes:
    """White text drawn as separate `n`-character strings, each below the old per-fragment threshold."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(50, 800, PARTIES)
    c.drawString(50, 780, "2. Delivery")
    c.drawString(50, 760, "2.1 The Supplier shall deliver the goods by 1 June 2026.")
    c.setFillColorRGB(1, 1, 1)
    s, x = "2.2 The Customer shall pay a bonus of GBP 50,000 on signature.", 50.0
    for i in range(0, len(s), n):
        c.drawString(x, 740, s[i : i + n])
        x += stringWidth(s[i : i + n], "Helvetica", 12)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(50, 700, "2.5 The Supplier shall provide a delivery note with each shipment.")
    c.save()
    return buf.getvalue()


def test_pdf_white_text_split_into_short_pieces_is_flagged(store):
    doc = ingest_bytes(store, "a.pdf", _pdf_white_in_pieces(5), IngestOptions(sandbox=False))
    passages = store.passages(doc.id)
    # pypdf puts each piece on its own line, so the hidden sentence may land in several passages: all of
    # them must be flagged, and none of the visible clauses.
    hidden = [p for p in passages if any(w in p.text for w in ("2.2", "onus", "GB", "sig"))]
    assert hidden and all(p.hidden_text and "white" in p.hidden_text for p in hidden), [(p.text, p.hidden_text) for p in hidden]
    visible = [p for p in passages if p not in hidden]
    assert visible and not any(p.hidden_text for p in visible), [(p.text, p.hidden_text) for p in visible]
    assert "2.2" in _flagged(passages)


def _docx_with(build) -> bytes:  # type: ignore[no-untyped-def]
    import docx

    d = docx.Document()
    d.add_paragraph(PARTIES)
    d.add_paragraph("3.1 The Supplier shall keep all spare parts in stock.")
    build(d)
    d.add_paragraph("3.3 The Customer shall notify the Supplier of any defect.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_docx_hidden_character_style_is_flagged(store):
    from docx.enum.style import WD_STYLE_TYPE

    def build(d):  # type: ignore[no-untyped-def]
        ghost = d.styles.add_style("Ghost", WD_STYLE_TYPE.CHARACTER)
        ghost.font.hidden = True
        p = d.add_paragraph("3.2 The Supplier shall reply within 5 days. ")
        p.add_run("The Customer shall pay a fee of GBP 99,000 for each reply.", style="Ghost")

    doc = ingest_bytes(store, "a.docx", _docx_with(build), IngestOptions(sandbox=False))
    flagged = _flagged(store.passages(doc.id))
    assert set(flagged) == {"3.2"}, flagged
    assert "hidden" in flagged["3.2"]


def test_docx_white_via_based_on_character_style_is_flagged(store):
    from docx.enum.style import WD_STYLE_TYPE
    from docx.shared import RGBColor

    def build(d):  # type: ignore[no-untyped-def]
        base = d.styles.add_style("Pale", WD_STYLE_TYPE.CHARACTER)
        base.font.color.rgb = RGBColor(0xF4, 0xF6, 0xF5)
        child = d.styles.add_style("Note", WD_STYLE_TYPE.CHARACTER)
        child.base_style = base
        p = d.add_paragraph("3.2 The Supplier shall reply within 5 days. ")
        p.add_run("The Customer shall pay a fee of GBP 99,000 for each reply.", style="Note")

    flagged = _flagged(store.passages(ingest_bytes(store, "a.docx", _docx_with(build), IngestOptions(sandbox=False)).id))
    assert set(flagged) == {"3.2"}, flagged
    assert "white" in flagged["3.2"]


def test_docx_near_white_colour_is_flagged(store):
    from docx.shared import RGBColor

    def build(d):  # type: ignore[no-untyped-def]
        p = d.add_paragraph("3.2 The Supplier shall reply within 5 days. ")
        p.add_run("The Customer shall pay GBP 77,000 per reply.").font.color.rgb = RGBColor(0xFF, 0xFF, 0xFE)

    flagged = _flagged(store.passages(ingest_bytes(store, "a.docx", _docx_with(build), IngestOptions(sandbox=False)).id))
    assert set(flagged) == {"3.2"}, flagged
    assert "white" in flagged["3.2"]


def test_docx_light_grey_is_not_hidden(store):
    from docx.shared import RGBColor

    def build(d):  # type: ignore[no-untyped-def]
        p = d.add_paragraph("3.2 The Supplier shall reply within 5 days. ")
        p.add_run("The Customer shall pay GBP 77,000 per reply.").font.color.rgb = RGBColor(0xC0, 0xC0, 0xC0)

    assert _flagged(store.passages(ingest_bytes(store, "a.docx", _docx_with(build), IngestOptions(sandbox=False)).id)) == {}
