"""Optional OCR for scanned PDFs (roadmap v0.2 #4). The real engine is an optional extra; tests use a fake."""

from __future__ import annotations

import io
import time

from claimtrace.core.models import Commitment
from claimtrace.extraction import analyze_document
from claimtrace.ingestion import IngestOptions, ingest_bytes, ocr, sandbox
from claimtrace.ingestion.parsers import parse_pdf


def _scanned_pdf(pages: int = 2) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for _ in range(pages):
        c.rect(50, 50, 400, 600, fill=1)  # an "image" of a page: no text layer
        c.showPage()
    c.save()
    return buf.getvalue()


PAGES = {
    1: ('This Agreement is made between Acme Ltd (the "Supplier") and Bolt plc (the "Customer").\n\n'
        "2.1 The Supplier shall deliver the goods by 1 June 2026.", 91.5),
    2: ("3.1 The Customer shall pay each invoice within 30 days of receipt.", 48.0),
}


def fake_ocr(data: bytes, pages: list[int]) -> dict[int, tuple[str, float]]:
    assert data.startswith(b"%PDF-")
    return {p: PAGES[p] for p in pages}


def test_without_tesseract_scanned_pdfs_stay_flagged_as_before(store, monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    assert ocr.default_ocr() is None
    raw = parse_pdf(_scanned_pdf())
    assert raw.blocks == []
    assert raw.warnings == [
        "SCANNED: This PDF has little or no text layer (it may be a scanned image). "
        "ClaimTrace v0.1 cannot read images, so results will be incomplete or empty."
    ]
    doc = ingest_bytes(store, "scan.pdf", _scanned_pdf(), IngestOptions(sandbox=False))
    assert any(w.startswith("SCANNED:") for w in doc.warnings)
    assert store.passages(doc.id) == []


def test_fake_ocr_reads_scanned_pages_with_per_page_confidence(store):
    doc = ingest_bytes(store, "scan.pdf", _scanned_pdf(), IngestOptions(sandbox=False, ocr=fake_ocr, doc_type="contract"))
    ps = store.passages(doc.id)
    assert {p.page for p in ps} == {1, 2}
    assert {p.ocr_confidence for p in ps} == {91.5, 48.0}
    assert not any(w.startswith("SCANNED:") for w in doc.warnings)
    ocr_warn = next(w for w in doc.warnings if w.startswith("OCR:"))
    assert "page 2" in ocr_warn and "48" in ocr_warn

    analyze_document(store, doc.id)
    cs = {c.section_number: c for c in store.objects(Commitment, doc.id)}
    low = cs["3.1"]
    assert any("OCR" in cv and "48" in cv for cv in low.caveats) and low.needs_review
    assert not any("OCR" in cv for cv in cs["2.1"].caveats)
    # quotes still verify against the stored (OCR) text
    text = store.get_document_text(doc.id)
    assert text[low.provenance.span.char_start : low.provenance.span.char_end] == low.text


def test_ocr_only_runs_on_pages_without_a_text_layer():
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(50, 800, "1.1 The Supplier shall keep the premises clean and tidy at all times.")
    c.showPage()
    c.rect(50, 50, 400, 600, fill=1)
    c.showPage()
    c.save()
    seen: list[list[int]] = []

    def spy(data: bytes, pages: list[int]) -> dict[int, tuple[str, float]]:
        seen.append(pages)
        return {2: ("3.1 The Customer shall pay each invoice within 30 days of receipt.", 88.0)}

    raw = parse_pdf(buf.getvalue(), ocr=spy)
    assert seen == [[2]]
    assert [b.page for b in raw.blocks] == [1, 2]
    assert raw.blocks[0].ocr_confidence is None and raw.blocks[1].ocr_confidence == 88.0


def test_ocr_failure_falls_back_to_the_scanned_warning():
    def broken(data: bytes, pages: list[int]) -> dict[int, tuple[str, float]]:
        raise RuntimeError("tesseract crashed")

    raw = parse_pdf(_scanned_pdf(), ocr=broken)
    assert raw.blocks == [] and any(w.startswith("SCANNED:") for w in raw.warnings)
    assert any("OCR failed" in w for w in raw.warnings)


# ---- OCR runs in its own sandboxed step with a per-page budget (regression vs v0.1, code review)
# The fakes below are module-level so the sandbox's child process can import them.


def fast_then_hanging_ocr(data: bytes, pages: list[int]) -> dict[int, tuple[str, float]]:
    out = {}
    for p in pages:
        if p > 2:
            time.sleep(120)  # a page the engine cannot finish in time
        out[p] = (f"{p}.1 The Supplier shall deliver lot {p} within 30 days of each purchase order.", 88.0)
    return out


def hanging_ocr(data: bytes, pages: list[int]) -> dict[int, tuple[str, float]]:
    time.sleep(120)
    return {}


def failing_ocr(data: bytes, pages: list[int]) -> dict[int, tuple[str, float]]:
    raise RuntimeError("engine crashed")


def _fast_limits(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sandbox, "OCR_PAGE_SECONDS", 1.0)
    monkeypatch.setattr(sandbox, "OCR_STARTUP_SECONDS", 2.0)


def test_sandboxed_ocr_reads_pages_like_in_process(store):
    doc = ingest_bytes(store, "scan.pdf", _scanned_pdf(), IngestOptions(sandbox=True, ocr=fake_ocr, doc_type="contract"))
    assert {p.page for p in store.passages(doc.id)} == {1, 2}
    assert {p.ocr_confidence for p in store.passages(doc.id)} == {91.5, 48.0}
    assert not any(w.startswith("SCANNED:") for w in doc.warnings)


def test_slow_ocr_in_sandbox_keeps_the_document_with_partial_ocr(store, monkeypatch):
    _fast_limits(monkeypatch)
    t = time.monotonic()
    doc = ingest_bytes(store, "scan.pdf", _scanned_pdf(4), IngestOptions(sandbox=True, ocr=fast_then_hanging_ocr))
    assert time.monotonic() - t < 45
    assert {p.page for p in store.passages(doc.id)} == {1, 2}
    partial = next(w for w in doc.warnings if "time limit" in w)
    assert partial.startswith("OCR:") and "3, 4" in partial


def test_hanging_ocr_in_sandbox_is_accepted_as_scanned(store, monkeypatch):
    """v0.1 accepted a scan with a SCANNED warning; v0.2 must not reject it because OCR ran out of time."""
    _fast_limits(monkeypatch)
    doc = ingest_bytes(store, "scan.pdf", _scanned_pdf(2), IngestOptions(sandbox=True, ocr=hanging_ocr))
    assert store.passages(doc.id) == []
    assert any(w.startswith("SCANNED:") for w in doc.warnings)
    assert any("time limit" in w for w in doc.warnings)


def test_failing_ocr_in_sandbox_keeps_the_text_layer(store, monkeypatch):
    _fast_limits(monkeypatch)
    doc = ingest_bytes(store, "scan.pdf", _scanned_pdf(2), IngestOptions(sandbox=True, ocr=failing_ocr))
    assert any(w.startswith("OCR failed") for w in doc.warnings)
    assert any(w.startswith("SCANNED:") for w in doc.warnings)
