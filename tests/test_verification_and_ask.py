import datetime as dt

from claimtrace.core.models import AnswerStatus, Verdict
from claimtrace.verification import NOT_FOUND, answer_question, verify_documents


def _by_section(run):
    return {f.subject_span.section: f for f in run.findings if f.subject_span}


def test_contract_vs_amendment(store, loaded):
    run = verify_documents(store, loaded["msa-v1.md"], loaded["amendment-1.md"])
    assert run.mode == "amendment"
    f = _by_section(run)
    assert f["2.1"].verdict == Verdict.contradicted and "15 May 2026" in f["2.1"].explanation
    assert f["3.2"].verdict == Verdict.contradicted and "30 vs 45" in f["3.2"].explanation
    assert f["3.1"].verdict == Verdict.contradicted and "110,000" in f["3.1"].explanation  # change by reference
    assert f["2.2"].verdict == Verdict.not_addressed


def test_contract_vs_audit_report(store, loaded):
    run = verify_documents(store, loaded["msa-v1.md"], loaded["audit-report-2026.md"])
    assert run.mode == "evidence"
    by_text = {f.subject_text: f for f in run.findings}
    loc = next(f for t, f in by_text.items() if "transfer Customer data" in t)
    assert loc.verdict == Verdict.contradicted and "Ireland" in loc.explanation
    mfa = next(f for t, f in by_text.items() if "multi-factor" in t)
    assert mfa.verdict == Verdict.partially_supported and mfa.sufficiency == "reviewer_judgement_required"
    sla = next(f for t, f in by_text.items() if "available 99.5%" in t)
    assert sla.verdict == Verdict.contradicted
    pen = next(f for t, f in by_text.items() if "penetration" in t)
    assert pen.verdict == Verdict.not_addressed  # auditor did not test it: not evidence either way
    notify = next(f for t, f in by_text.items() if "personal data breach" in t)
    assert notify.verdict == Verdict.needs_human_review  # same hours, different starting event
    assert all(f.verdict != Verdict.consistent or f.sufficiency for f in run.findings)


def test_delivery_checked_against_amended_deadline(store, loaded):
    run = verify_documents(store, loaded["msa-v1.md"], loaded["delivery-record.md"])
    late = next(f for f in run.findings if "deliver the Phase 1" in f.subject_text and f.verdict == Verdict.contradicted)
    assert "7 days late" in late.explanation


def test_not_found_uses_exact_wording(store, loaded):
    a = answer_question(store, "What is the liability cap?")
    assert a.status == AnswerStatus.not_addressed and a.answer_text == NOT_FOUND


def test_answer_mentions_amendment(store, loaded):
    a = answer_question(store, "Did the vendor promise delivery by March 31?")
    assert a.status == AnswerStatus.stated
    assert a.answer_text.startswith("Originally yes")
    assert any("May 15, 2026" in c.span.quote for c in a.citations)
    assert all(c.verified for c in a.citations)


def test_current_terms_lead(store, loaded):
    a = answer_question(store, "How many days does the customer have to pay invoices?")
    assert a.citations[0].span.quote.endswith("within 45 days of receipt.")


def test_cross_document_contradiction(store, loaded):
    a = answer_question(store, "Is customer data kept in the UK?")
    assert a.status == AnswerStatus.contradicted
    assert any(c.role == "conflicts" and "Dublin" in c.span.quote for c in a.citations)


def test_consequence_question_includes_qualifier(store, loaded):
    a = answer_question(store, "What happens if the vendor misses the delivery deadline?")
    assert "liquidated damages" in a.citations[0].span.quote
    assert any("does not apply" in c.span.quote for c in a.citations)


def test_due_soon_and_changed(store, loaded):
    a = answer_question(store, "What commitments are due in the next 30 days?", today=dt.date(2026, 5, 1))
    assert "15 May 2026" in a.answer_text
    b = answer_question(store, "Which commitments changed in the amendment?")
    assert b.status == AnswerStatus.stated and "45 days" in b.answer_text


def test_scope_caveat_always_present(store, loaded):
    a = answer_question(store, "Does the audit report support that encryption at rest is implemented?")
    assert any("Only covers the documents" in c for c in a.caveats)
