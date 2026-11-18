"""Business-day calendars: "10 Business Days" becomes a date when its anchor resolves (roadmap v0.2 #8)."""

from __future__ import annotations

import datetime as dt

import pytest

from claimtrace.core.models import Commitment
from claimtrace.extraction import analyze_document
from claimtrace.extraction.calendar import add_business_days, load_holidays
from claimtrace.extraction.patterns import extract_deadline
from claimtrace.ingestion import IngestOptions, ingest_bytes

D = dt.date


def test_weekends_are_skipped():
    assert add_business_days(D(2026, 1, 2), 1) == D(2026, 1, 5)  # Friday + 1 -> Monday
    assert add_business_days(D(2026, 1, 3), 1) == D(2026, 1, 5)  # Saturday + 1 -> Monday
    assert add_business_days(D(2026, 3, 2), 10) == D(2026, 3, 16)
    assert add_business_days(D(2026, 3, 2), 0) == D(2026, 3, 2)


def test_holidays_are_skipped():
    assert add_business_days(D(2026, 1, 2), 1, frozenset({D(2026, 1, 5)})) == D(2026, 1, 6)


def test_business_day_deadline_with_resolved_anchor_gets_a_date():
    s = "The Supplier shall deliver the plan within 10 Business Days of the Effective Date."
    d = extract_deadline(s, D(2026, 3, 2))
    assert d.business_days and d.offset_days == 10 and d.date == D(2026, 3, 16)
    d2 = extract_deadline(s, D(2026, 3, 2), frozenset({D(2026, 3, 9)}))
    assert d2.date == D(2026, 3, 17)


def test_unresolved_anchor_stays_unresolved():
    d = extract_deadline("The Supplier shall respond within 10 Business Days of receipt of a request.", D(2026, 3, 2))
    assert d.business_days and d.date is None and d.anchor


def test_no_reference_date_stays_unresolved():
    d = extract_deadline("The Supplier shall deliver within 5 working days of the Commencement Date.", None)
    assert d.business_days and d.date is None


def test_load_holidays_file(tmp_path):
    f = tmp_path / "hol.txt"
    f.write_text("# UK bank holidays\n2026-04-03\n\n2026-04-06  # Easter Monday\n")
    assert load_holidays(str(f)) == frozenset({D(2026, 4, 3), D(2026, 4, 6)})


def test_bad_holiday_file_fails_loudly(tmp_path):
    f = tmp_path / "hol.txt"
    f.write_text("2026-04-03\n03/04/2026\n")
    with pytest.raises(ValueError, match="line 2"):
        load_holidays(str(f))
    with pytest.raises(ValueError):
        load_holidays(str(tmp_path / "missing.txt"))


def test_holidays_env_is_used_by_analysis(store, tmp_path, monkeypatch):
    f = tmp_path / "hol.txt"
    f.write_text("2026-03-09\n")
    monkeypatch.setenv("CLAIMTRACE_HOLIDAYS", str(f))
    text = ('This Agreement is dated 2 March 2026 and is made between Acme Ltd (the "Supplier") and Bolt plc '
            '(the "Customer").\n\n1.1 The Supplier shall deliver the plan within 10 Business Days of the date of '
            "this Agreement.\n")
    doc = ingest_bytes(store, "a.md", text.encode(), IngestOptions(doc_type="contract", sandbox=False))
    run = analyze_document(store, doc.id)
    c = store.objects(Commitment, doc.id)[0]
    assert c.deadline is not None and c.deadline.date == D(2026, 3, 17)
    assert any("holiday" in cv for cv in c.caveats)
    assert run.run_manifest["holiday_calendar"]["count"] == 1
