"""DOCX tables keep row/cell structure as passages so commitments in tables are found and quotes verify."""

from __future__ import annotations

import datetime as dt
import io

from claimtrace.core.models import Commitment
from claimtrace.extraction import analyze_document
from claimtrace.ingestion import IngestOptions, ingest_bytes


def _docx() -> bytes:
    import docx

    d = docx.Document()
    d.add_paragraph('This Agreement is made between Acme Ltd (the "Supplier") and Bolt plc (the "Customer").')
    d.add_heading("4. Deliverables", level=1)
    d.add_paragraph("4.1 The Supplier shall deliver the items in the table below.")
    t = d.add_table(rows=4, cols=3)
    for r, row in enumerate([("Item", "Obligation", "Due date"),
                             ("1", "The Supplier shall deliver the training manual.", "15 May 2026"),
                             ("2", "The Customer shall provide site access.", "within 5 days of request"),
                             ("Note", "", "")]):
        for c, val in enumerate(row):
            t.cell(r, c).text = val
    t.cell(3, 0).merge(t.cell(3, 2))  # one merged cell spanning the row
    t.cell(3, 0).text = "Dates may move by agreement."
    d.add_paragraph("4.2 The Customer shall pay for each item on delivery.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_rows_become_passages_in_document_order(store):
    doc = ingest_bytes(store, "a.docx", _docx(), IngestOptions(sandbox=False))
    ps = store.passages(doc.id)
    texts = [p.text for p in ps]
    i = texts.index("4.1 The Supplier shall deliver the items in the table below.")
    assert texts[i + 1] == "Item | Obligation | Due date"
    assert texts[i + 2] == "1 | The Supplier shall deliver the training manual. | 15 May 2026"
    assert texts[i + 4] == "Dates may move by agreement."  # merged cells are not repeated
    assert texts[i + 5] == "4.2 The Customer shall pay for each item on delivery."
    assert [p.locator for p in ps[i + 1 : i + 5]] == ["table 1, row 1", "table 1, row 2", "table 1, row 3", "table 1, row 4"]
    assert ps[i + 2].section_number == "4.1" and ps[i].locator is None


def test_commitments_in_table_cells_are_extracted_and_verify(store):
    doc = ingest_bytes(store, "a.docx", _docx(), IngestOptions(sandbox=False, doc_type="contract"))
    analyze_document(store, doc.id)
    cs = {c.text: c for c in store.objects(Commitment, doc.id)}
    manual = cs["The Supplier shall deliver the training manual."]
    assert manual.obliging_party == "Supplier"
    assert manual.provenance.span.locator == "table 1, row 2"
    assert manual.deadline is not None and manual.deadline.date == dt.date(2026, 5, 15)
    assert any("same table row" in cv for cv in manual.caveats)
    access = cs["The Customer shall provide site access."]
    assert access.obliging_party == "Customer" and access.deadline and access.deadline.kind == "relative"
    text = store.get_document_text(doc.id)
    for c in (manual, access):
        s = c.provenance.span
        assert text[s.char_start : s.char_end] == c.text
    assert not any(" | " in c.text for c in cs.values())
