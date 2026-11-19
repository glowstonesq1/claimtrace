"""claimtrace.browser: the in-process facade the try page runs in Pyodide, tested in normal CPython."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from claimtrace.browser import MAX_FILE_BYTES, Session, call

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "documents"
SAMPLES = ("amendment-1.md", "audit-report-2026.md", "delivery-record.md", "msa-v1.md")  # amendment first on purpose


def _files(*names: str) -> list[dict]:
    return [{"name": n, "bytes": (EXAMPLES / n).read_bytes()} for n in names]


@pytest.fixture
def session() -> Session:
    return Session()


@pytest.fixture
def samples(session: Session) -> dict:
    return session.analyze(_files(*SAMPLES))


def _ids(reg: dict) -> dict[str, str]:
    return {d["filename"]: d["id"] for d in reg["documents"]}


def test_samples_register(samples: dict) -> None:
    assert [w for w in samples["warnings"] if w["code"] != "note"] == []
    assert len(samples["documents"]) == 4
    ids = _ids(samples)
    amd = next(d for d in samples["documents"] if d["filename"] == "amendment-1.md")
    # given before the contract, the amendment is still linked to it
    assert amd["amends_document_id"] == ids["msa-v1.md"]
    assert len(samples["commitments"]) >= 20
    parties = {c["obliging_party"] for c in samples["commitments"]}
    assert {"Vendor", "Customer"} <= parties
    assert {(p["name"], p["alias"]) for p in samples["parties"]} >= {("Corvane Software Ltd.", "Vendor"),
                                                                     ("Halden Freight Co.", "Customer")}
    assert any(d["date"] == "2026-05-15" for d in samples["deadlines"])


def test_every_quote_verifies(session: Session, samples: dict) -> None:
    assert samples["integrity"]["quotes"] == len(samples["commitments"])
    assert samples["integrity"]["verified"] == samples["integrity"]["quotes"]
    texts = {d["id"]: session.document(d["id"])["text"] for d in samples["documents"]}
    for c in samples["commitments"]:
        q = c["quote"]
        assert q["verified"] is True, c["id"]
        assert texts[q["document_id"]][q["char_start"] : q["char_end"]] == q["quote"]


def test_replaced_by_amendment(samples: dict) -> None:
    c21 = next(c for c in samples["commitments"] if c["section"] == "2.1" and c["document"] == "Master Services Agreement")
    assert c21["document_effect"] == "replaced"
    assert c21["status"] == "superseded"
    assert any("May 15, 2026" in r["text"] for r in c21["replaced_by"])
    assert any(c.startswith("Replaced by ") for c in c21["caveats"])


def test_ask_with_verified_quotes(session: Session, samples: dict) -> None:
    ans = session.ask("Did the vendor promise delivery by March 31?")
    assert ans["status"] == "stated"
    assert "later changed" in ans["answer_text"]
    quotes = [c["span"]["quote"] for c in ans["citations"]]
    assert any("March 31, 2026" in q for q in quotes) and any("May 15, 2026" in q for q in quotes)
    assert all(c["verified"] and c["span"]["verified"] for c in ans["citations"])


def test_ask_not_found(session: Session, samples: dict) -> None:
    ans = session.ask("What is the liability cap?")
    assert ans["status"] == "not_addressed"


def test_verify_contract_against_delivery_record(session: Session, samples: dict) -> None:
    ids = _ids(samples)
    run = session.verify(ids["msa-v1.md"], ids["delivery-record.md"])
    assert run["mode"] == "evidence"
    first = run["findings"][0]
    assert first["verdict"] == "contradicted" and first["severity"] == "high"
    assert "late" in first["explanation"]
    sev = [f["severity"] for f in run["findings"] if not f["routine"]]
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    assert sev == sorted(sev, key=order.__getitem__)
    for f in run["findings"]:
        for s in [f["subject_span"], *f["supporting"], *f["conflicting"]]:
            assert s is None or s["verified"] is True


def test_verify_contract_against_amendment(session: Session, samples: dict) -> None:
    ids = _ids(samples)
    run = session.verify(ids["msa-v1.md"], ids["amendment-1.md"])
    assert run["mode"] == "amendment"
    assert [f for f in run["findings"] if not f["routine"]]
    assert all(f["routine"] for f in run["findings"][len([f for f in run["findings"] if not f["routine"]]):])


def test_pdf_and_docx(session: Session) -> None:
    from docx import Document as Docx
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    y = 780
    for line in ("Supply Agreement", "This Supply Agreement is made between Arden Mills Ltd. (the \"Supplier\") and",
                 "Brook Foods plc (the \"Buyer\").", "1. Delivery",
                 "1.1 The Supplier shall deliver the goods no later than June 30, 2026."):
        pdf.drawString(72, y, line)
        y -= 18
    pdf.save()
    d = Docx()
    d.add_heading("Service Order", level=1)
    d.add_paragraph('This Service Order is between Kestrel Labs Ltd. (the "Provider") and Mere Holdings Ltd. (the "Client").')
    d.add_paragraph("1. The Provider shall deliver the monthly report within 5 Business Days of each month end.")
    dbuf = io.BytesIO()
    d.save(dbuf)
    reg = session.analyze([{"name": "supply.pdf", "bytes": buf.getvalue()}, {"name": "order.docx", "bytes": dbuf.getvalue()}])
    assert {d["filename"] for d in reg["documents"]} == {"supply.pdf", "order.docx"}
    texts = {c["text"] for c in reg["commitments"]}
    assert any("June 30, 2026" in t for t in texts)
    assert any("monthly report" in t for t in texts)
    assert reg["integrity"]["verified"] == reg["integrity"]["quotes"] > 0


def test_rejected_files_do_not_stop_the_rest(session: Session) -> None:
    reg = session.analyze([
        {"name": "fake.pdf", "bytes": b"not a pdf"},
        {"name": "notes.exe", "bytes": b"MZ"},
        {"name": "empty.txt", "bytes": b""},
        {"name": "big.txt", "bytes": b"a" * (MAX_FILE_BYTES + 1)},
        *_files("msa-v1.md"),
    ])
    codes = {w["file"]: w["code"] for w in reg["warnings"]}
    assert codes["fake.pdf"] == "type_mismatch"
    assert codes["notes.exe"] == "unsupported_file_type"
    assert codes["empty.txt"] == "empty_file"
    assert codes["big.txt"] == "file_too_large"
    assert [d["filename"] for d in reg["documents"]] == ["msa-v1.md"]


def test_same_file_twice_is_stored_once(session: Session) -> None:
    session.analyze(_files("msa-v1.md"))
    reg = session.analyze(_files("msa-v1.md"))
    assert len(reg["documents"]) == 1


def test_call_round_trip() -> None:
    files = _files("msa-v1.md", "delivery-record.md")
    out = json.loads(call(json.dumps({"op": "reset"})))
    assert out["ok"] and out["result"]["documents"] == []
    out = json.loads(call(json.dumps({"op": "analyze"}), files))
    assert out["ok"] and len(out["result"]["documents"]) == 2
    ids = _ids(out["result"])
    ans = json.loads(call(json.dumps({"op": "ask", "question": "When must the vendor deliver the Phase 1 System?"})))
    assert ans["ok"] and ans["result"]["citations"]
    ver = json.loads(call(json.dumps({"op": "verify", "base_id": ids["msa-v1.md"], "other_id": ids["delivery-record.md"]})))
    assert ver["ok"] and ver["result"]["findings"][0]["verdict"] == "contradicted"
    doc = json.loads(call(json.dumps({"op": "document", "doc_id": ids["msa-v1.md"]})))
    assert doc["ok"] and doc["result"]["passages"]
    md = json.loads(call(json.dumps({"op": "export", "format": "md"})))
    assert md["ok"] and "not legal advice" in md["result"]
    js = json.loads(json.loads(call(json.dumps({"op": "export", "format": "json"})))["result"])
    assert js["reports"] and js["reports"][0]["schema"] == "claimtrace.report/v1"
    bad = json.loads(call(json.dumps({"op": "nope"})))
    assert bad == {"ok": False, "error": {"code": "unknown_op", "message": "Unknown operation 'nope'."}}
    missing = json.loads(call(json.dumps({"op": "document", "doc_id": "doc_missing"})))
    assert missing["ok"] is False and "doc_missing" not in missing["error"]["message"]
    call(json.dumps({"op": "reset"}))


def test_browser_path_imports_no_server_or_network_modules() -> None:
    code = (
        "import sys, json\n"
        "import claimtrace.browser as b\n"
        "from pathlib import Path\n"
        f"p = Path({str(EXAMPLES)!r})\n"
        "b.analyze([{'name': n, 'bytes': (p / n).read_bytes()} for n in ('msa-v1.md', 'amendment-1.md')])\n"
        "b.ask('Did the vendor promise delivery by March 31?')\n"
        "print(json.dumps(sorted(m for m in sys.modules if m.split('.')[0] in "
        "('fastapi', 'uvicorn', 'httpx', 'starlette', 'anyio') or m == 'claimtrace.ingestion.sandbox')))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == []


def test_server_ingest_still_uses_the_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    from claimtrace.core.store import Store
    from claimtrace.ingestion import IngestOptions, ingest_bytes, sandbox

    seen: list[str] = []
    real = sandbox.parse_sandboxed

    def spy(kind: str, data: bytes, ocr=None):  # type: ignore[no-untyped-def]
        seen.append(kind)
        return real(kind, data, ocr)

    monkeypatch.setattr(sandbox, "parse_sandboxed", spy)
    doc = ingest_bytes(Store(), "msa-v1.md", (EXAMPLES / "msa-v1.md").read_bytes(), IngestOptions())
    assert seen == ["md"] and doc.title == "Master Services Agreement"
