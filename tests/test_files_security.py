"""Malicious and real-file ingestion tests (design-review D12, security reviewer)."""

import io
import zipfile

import pytest

from claimtrace.ingestion import IngestError, IngestOptions, ingest_bytes
from claimtrace.ingestion.parsers import detect_kind, parse_docx


def _pdf(text_lines: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in text_lines:
        if line == "<PAGE>":
            c.showPage()
            y = 800
            continue
        c.drawString(50, y, line)
        y -= 18
    c.save()
    return buf.getvalue()


def _docx(paragraphs: list[str]) -> bytes:
    import docx

    d = docx.Document()
    d.core_properties.title = "Test Agreement"
    d.add_heading("2. Delivery", level=1)
    for p in paragraphs:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.mark.parametrize("sandbox", [False, True])
def test_real_pdf_keeps_pages_and_sections(store, sandbox):
    data = _pdf(['This Agreement is made between Acme Ltd (the "Supplier") and Bolt plc (the "Customer").',
                 "2. Delivery", "2.1 The Supplier shall deliver the goods by 1 June 2026.", "<PAGE>",
                 "3. Payment", "3.1 The Customer shall pay within 30 days of invoice."])
    doc = ingest_bytes(store, "a.pdf", data, IngestOptions(sandbox=sandbox))
    ps = store.passages(doc.id)
    pay = next(p for p in ps if "shall pay" in p.text)
    assert pay.page == 2 and pay.section_number == "3.1"
    assert doc.page_count == 2


def test_scanned_pdf_is_flagged_loudly(store):
    doc = ingest_bytes(store, "scan.pdf", _pdf(["<PAGE>"]), IngestOptions(sandbox=False))
    assert any(w.startswith("SCANNED") for w in doc.warnings)


def test_real_docx(store):
    doc = ingest_bytes(store, "a.docx", _docx(["2.1 The Supplier shall deliver the goods."]),
                       IngestOptions(sandbox=False))
    assert doc.title == "Test Agreement"
    assert any(p.section_number == "2.1" for p in store.passages(doc.id))


def test_type_mismatch_and_unsupported():
    with pytest.raises(IngestError) as e:
        detect_kind("a.pdf", b"PK\x03\x04 not a pdf")
    assert e.value.code == "type_mismatch"
    with pytest.raises(IngestError) as e:
        detect_kind("a.exe", b"MZ")
    assert e.value.code == "unsupported_file_type"


@pytest.mark.parametrize("payload", [
    b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><w:document>&xxe;</w:document>',
    b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">'
    b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;">]><w:document>&c;</w:document>',
])
def test_docx_entity_attacks_rejected(payload):
    data = _zip({"[Content_Types].xml": b"<Types/>", "word/document.xml": payload})
    with pytest.raises(IngestError) as e:
        parse_docx(data)
    assert e.value.code == "unsafe_content"


def test_docx_zip_bomb_rejected():
    data = _zip({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<a>" + b"A" * 60_000_000 + b"</a>"})
    with pytest.raises(IngestError) as e:
        parse_docx(data)
    assert e.value.code in ("unsafe_content", "file_too_large")


def test_docx_macros_rejected():
    data = _zip({"[Content_Types].xml": b"<Types/>", "word/vbaProject.bin": b"\x00\x01"})
    with pytest.raises(IngestError) as e:
        parse_docx(data)
    assert e.value.code == "unsafe_content"


def test_pdf_with_javascript_rejected(store):
    data = b"%PDF-1.4\n1 0 obj << /Type /Catalog /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >> endobj\n%%EOF"
    with pytest.raises(IngestError) as e:
        ingest_bytes(store, "x.pdf", data, IngestOptions(sandbox=False))
    assert e.value.code == "unsafe_content"


def test_sandbox_contains_parser_crash(store):
    with pytest.raises(IngestError) as e:
        ingest_bytes(store, "broken.pdf", b"%PDF-1.4\n" + b"\x00garbage" * 100, IngestOptions(sandbox=True))
    assert e.value.code in ("corrupt_file", "parse_failed", "resource_limit")


def test_oversized_upload_rejected(store):
    from claimtrace.ingestion.pipeline import MAX_UPLOAD_BYTES

    with pytest.raises(IngestError) as e:
        ingest_bytes(store, "big.txt", b"a" * (MAX_UPLOAD_BYTES + 1), IngestOptions(sandbox=False))
    assert e.value.code == "file_too_large"
