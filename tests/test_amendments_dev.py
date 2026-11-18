"""Amendment generalisation (v0.2) against hand-written dev fixtures in tests/fixtures/amendments_dev."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claimtrace.core.models import AmendmentInstruction, Commitment, DocumentEffect
from claimtrace.core.store import Store
from claimtrace.core.text import squash
from claimtrace.extraction import analyze_document
from claimtrace.extraction.amendments import number_tolerant_pattern, parse_instructions
from claimtrace.ingestion import IngestOptions, ingest_bytes
from claimtrace.verification import verify_documents

FIXTURES = Path(__file__).parent / "fixtures" / "amendments_dev"
CASES = sorted(FIXTURES.glob("*.case"))


def _load(path: Path) -> tuple[str, str, dict]:
    raw = path.read_text()
    _, rest = raw.split("=== base ===\n", 1)
    base, rest = rest.split("=== amendment ===\n", 1)
    amd, expected = rest.split("=== expected ===\n", 1)
    return base, amd, json.loads(expected)


def _run(base_md: str, amd_md: str, amd_type: str) -> tuple[Store, str, str]:
    store = Store()
    base = ingest_bytes(store, "base.md", base_md.encode(), IngestOptions(doc_type="contract", sandbox=False))
    amd = ingest_bytes(store, "change.md", amd_md.encode(),
                       IngestOptions(doc_type=amd_type, sandbox=False, amends_document_id=base.id))
    analyze_document(store, base.id)
    analyze_document(store, amd.id)
    return store, base.id, amd.id


def test_fixture_set_is_not_empty():
    assert len(CASES) >= 15


@pytest.mark.parametrize("path", CASES, ids=[p.stem for p in CASES])
def test_dev_case(path: Path):
    base_md, amd_md, exp = _load(path)
    store, base_id, amd_id = _run(base_md, amd_md, exp.get("amendment_type", "amendment"))
    base_cs = store.objects(Commitment, base_id)
    for section, effect in exp["effects"].items():
        cs = [c for c in base_cs if c.section_number == section]
        assert cs, f"no base commitment in section {section}: {[c.section_number for c in base_cs]}"
        assert {c.document_effect.value for c in cs} == {effect}, f"section {section}"
    instructions = store.objects(AmendmentInstruction, amd_id)
    if "actions" in exp:
        assert [i.action for i in instructions] == exp["actions"]
    assert sum(1 for i in instructions if i.needs_review) == exp.get("unresolved", 0)
    if "derived_contains" in exp:
        live = [c for c in store.objects(Commitment, amd_id) if c.document_effect == DocumentEffect.in_force]
        assert any(squash(exp["derived_contains"]) in squash(c.text) for c in live), [c.text for c in live]
    if "verdicts" in exp:
        run = verify_documents(store, base_id, amd_id)
        for v in exp["verdicts"]:
            f = [f for f in run.findings if squash(v["subject_contains"]) in squash(f.subject_text)]
            assert f, f"no finding for {v['subject_contains']!r}"
            assert f[0].verdict.value == v["verdict"], (v, f[0].explanation)


def test_unresolved_target_never_changes_the_base():
    base_md, amd_md, _ = _load(FIXTURES / "13_missing_target.case")
    store, base_id, amd_id = _run(base_md, amd_md, "amendment")
    bad = next(i for i in store.objects(AmendmentInstruction, amd_id) if i.target_section == "14.2")
    assert bad.needs_review and any("14.2" in r for r in bad.review_reasons)
    new = [c for c in store.objects(Commitment, amd_id) if c.amends_section == "14.2"]
    assert new and all(c.needs_review for c in new)


@pytest.mark.parametrize(
    ("text", "action", "target"),
    [
        ('Clause 4.1 is amended by deleting "99%" and inserting "99.9%".', "modify", "4.1"),
        ('Clause 2 shall be read as if the words "or its Affiliates" were deleted.', "modify", "2"),
        ("Clause 7 (Audit) is hereby deleted in its entirety.", "delete", "7"),
        ('The parties agree that clause 3.4 shall now read: "The Buyer shall collect the goods."', "replace", "3.4"),
        ("Schedule 3 is replaced in its entirety by the Schedule attached to this Amendment.", "replace", "Schedule 3"),
        ("Clause 9 is renumbered as clause 10.", "renumber", "9"),
        ('The clause headed "Liability" is deleted.', "delete", "title:Liability"),
        ('In clause 5.2 the words "ten (10) days" shall be replaced with "five (5) days".', "modify", "5.2"),
    ],
)
def test_parse_phrasings(text, action, target):
    got = parse_instructions(text)
    assert got, text
    assert (got[0].action, got[0].target) == (action, target)


def test_shall_be_read_as_if_deleted_gives_empty_replacement():
    ins = parse_instructions('Clause 2 shall be read as if the words "or its Affiliates" were deleted.')[0]
    assert ins.old_text == "or its Affiliates" and ins.new_text == ""


def test_number_tolerant_pattern_matches_word_and_digit_forms():
    import re

    rx = re.compile(number_tolerant_pattern("30 days"), re.I)
    for s in ("within 30 days", "within thirty (30) days", "within thirty days", "within 30 days'"):
        assert rx.search(s), s
    assert not rx.search("within 300 days")
    rx2 = re.compile(number_tolerant_pattern("forty-five (45) days"), re.I)
    assert rx2.search("pay within 45 days") and rx2.search("forty five days")
