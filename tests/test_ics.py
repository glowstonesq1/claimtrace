"""ICS export of resolved deadlines (roadmap v0.2 #10): RFC 5545, escaped text, no network."""

from __future__ import annotations

import datetime as dt
import socket

from claimtrace.cli.main import main as cli
from claimtrace.extraction import analyze_document
from claimtrace.ingestion import IngestOptions, ingest_bytes
from claimtrace.verification.report import deadlines_ics, ics_escape

TEXT = """---
title: Widget Supply Agreement
doc_type: contract
---
This Agreement is dated 2 March 2026 and is made between Acme, Widgets; and Co Ltd (the "Supplier") and Bolt plc (the "Customer").

1.1 The Supplier shall deliver the widgets, gaskets; and seals no later than 31 March 2026.

1.2 The Customer shall pay each invoice within 30 days of receipt.

1.3 The Supplier shall notify the Customer promptly of any delay.

1.4 The Supplier shall deliver the installation plan within 10 Business Days of the date of this Agreement.

1.5 The Supplier shall provide a written report describing every test performed on every batch of widgets,
gaskets and seals, including the results, the equipment used and the name of the engineer, by 30 April 2026.
"""


def _doc(store):
    doc = ingest_bytes(store, "supply.md", TEXT.encode(), IngestOptions(sandbox=False))
    analyze_document(store, doc.id)
    return doc


def _unfold(ics: str) -> list[str]:
    return ics.replace("\r\n ", "").split("\r\n")


def test_only_resolved_dates_become_events(store):
    doc = _doc(store)
    ics = deadlines_ics(store, doc.id, now=dt.datetime(2026, 3, 3, 9, 0, tzinfo=dt.UTC))
    lines = _unfold(ics)
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-2] == "END:VCALENDAR" and lines[-1] == ""
    assert "VERSION:2.0" in lines and any(x.startswith("PRODID:") for x in lines)
    starts = sorted(x for x in lines if x.startswith("DTSTART"))
    assert starts == ["DTSTART;VALUE=DATE:20260316", "DTSTART;VALUE=DATE:20260331", "DTSTART;VALUE=DATE:20260430"]
    assert lines.count("BEGIN:VEVENT") == 3
    assert "DTEND;VALUE=DATE:20260401" in lines
    assert "DTSTAMP:20260303T090000Z" in lines
    uids = [x for x in lines if x.startswith("UID:")]
    assert len(set(uids)) == 3


def test_text_is_escaped_and_lines_are_folded(store):
    doc = _doc(store)
    ics = deadlines_ics(store, doc.id)
    assert "\n" not in ics.replace("\r\n", "")  # CRLF only
    for raw_line in ics.split("\r\n"):
        assert len(raw_line.encode("utf-8")) <= 75
    summary = next(x for x in _unfold(ics) if x.startswith("SUMMARY:") and "widgets" in x)
    assert "widgets\\, gaskets\\; and seals" in summary
    assert ics_escape('a\\b;c,d\ne') == "a\\\\b\\;c\\,d\\ne"


def test_superseded_deadlines_are_left_out(store):
    doc = _doc(store)
    amd = ingest_bytes(store, "amd.md", (
        b'This Amendment is made between Acme Ltd (the "Supplier") and Bolt plc (the "Customer").\n\n'
        b'1. Clause 1.1 is amended to read: "The Supplier shall deliver the widgets no later than 15 April 2026."\n'
    ), IngestOptions(sandbox=False, doc_type="amendment", amends_document_id=doc.id))
    analyze_document(store, amd.id)
    lines = _unfold(deadlines_ics(store, doc.id))
    starts = [x for x in lines if x.startswith("DTSTART")]
    assert "DTSTART;VALUE=DATE:20260331" not in starts and "DTSTART;VALUE=DATE:20260415" in starts


def test_api_download_makes_no_network_calls(store, client, monkeypatch):
    doc = _doc(store)

    def no_network(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    r = client.get(f"/documents/{doc.id}/deadlines.ics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    assert "attachment" in r.headers["content-disposition"] and ".ics" in r.headers["content-disposition"]
    assert r.text.startswith("BEGIN:VCALENDAR\r\n")
    assert client.get("/documents/doc_missing/deadlines.ics").status_code == 404


def test_cli_report_ics(store, tmp_path, capsys):
    db = str(tmp_path / "ct.db")
    f = tmp_path / "supply.md"
    f.write_text(TEXT)
    assert cli(["--db", db, "ingest", str(f)]) == 0
    import json

    doc_id = json.loads(capsys.readouterr().out)["document_id"]
    assert cli(["--db", db, "report", doc_id, "--format", "ics"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("BEGIN:VCALENDAR") and out.count("BEGIN:VEVENT") == 3
