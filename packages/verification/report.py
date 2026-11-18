"""Audit report export: JSON (schema-versioned), Markdown, print-ready HTML, and a deadline CSV.

Every report embeds document checksums, re-verifies each quote against stored text, lists
unreviewed items prominently and states what was not checked (design-review §2 D8, audit reviewer).
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
from datetime import UTC, datetime

from claimtrace import __version__
from claimtrace.core.models import Commitment, DocumentEffect, Span
from claimtrace.core.store import Store

REPORT_SCHEMA = "claimtrace.report/v1"
DISCLAIMER = ("ClaimTrace is a document-review aid. It is not legal advice and does not determine what is true. "
              "Every item below quotes its source; check the quotes before relying on them.")
NOT_CHECKED = [
    "Documents that were not uploaded (later amendments, schedules, side letters, emails).",
    "Scanned pages or images without a text layer.",
    "Whether evidence is sufficient: located evidence text is not proof that an obligation was met.",
    "Legal effect, enforceability, governing-law or order-of-precedence questions.",
    "Meaning beyond typed comparisons (dates, amounts, percentages, durations, places, obligation strength).",
]


def _span_ok(store: Store, span: Span | None) -> bool:
    if span is None:
        return True
    text = store.get_document_text(span.document_id)
    return text[span.char_start : span.char_end] == span.quote


def build_report(store: Store, doc_id: str) -> dict:
    doc = store.get_document(doc_id)
    commitments = store.objects(Commitment, doc_id)
    amendments = [d for d in store.list_documents() if d.amends_document_id == doc_id]
    amendment_commitments = [c for d in amendments for c in store.objects(Commitment, d.id)]
    verifications = store.verifications_for_document(doc_id)
    answers = store.answers_for_document(doc_id)
    integrity_failures: list[str] = []

    def item(c: Commitment) -> dict:
        ok = _span_ok(store, c.provenance.span)
        if not ok:
            integrity_failures.append(c.id)
        return {
            "id": c.id, "section": c.section_number, "type": c.type.value, "modality": c.modality.value,
            "obliging_party": c.obliging_party, "beneficiary_party": c.beneficiary_party, "action": c.action,
            "deadline": c.deadline.model_dump(mode="json") if c.deadline else None, "conditions": c.conditions,
            "exceptions": c.exceptions, "document_effect": c.document_effect.value, "lifecycle": c.lifecycle.value,
            "status": c.status.value, "confidence": c.confidence.value, "needs_review": c.needs_review,
            "review_reasons": c.review_reasons, "caveats": c.caveats, "quote": c.text,
            "location": {"document_id": c.provenance.span.document_id, "document": c.provenance.span.document_title,
                         "version": c.provenance.span.document_version, "section": c.provenance.span.section,
                         "page": c.provenance.span.page, "char_start": c.provenance.span.char_start,
                         "char_end": c.provenance.span.char_end},
            "quote_verified": ok, "review_status": store.current_review_status(c.id).value,
            "extraction": {"method": c.provenance.extraction_method, "extractor": c.provenance.extractor_version,
                           "model": c.provenance.model, "prompt_version": c.provenance.prompt_version},
        }

    findings = []
    for run in verifications:
        for f in run.findings:
            spans = [f.subject_span, *f.supporting, *f.conflicting]
            ok = all(_span_ok(store, s) for s in spans)
            if not ok:
                integrity_failures.append(f.id)
            findings.append({
                "id": f.id, "run_id": run.id, "mode": run.mode, "verdict": f.verdict.value,
                "severity": f.severity.value, "subject": f.subject_text, "explanation": f.explanation,
                "recommended_action": f.recommended_action, "sufficiency": f.sufficiency,
                "supporting": [s.model_dump(mode="json") for s in f.supporting],
                "conflicting": [s.model_dump(mode="json") for s in f.conflicting],
                "quotes_verified": ok, "review_status": store.current_review_status(f.id).value,
            })
    review_targets = {c.id for c in commitments} | {f["id"] for f in findings} | {a.id for a in answers}
    trail = [r.model_dump(mode="json") for r in store.reviews() if r.target_id in review_targets]
    items = [item(c) for c in commitments] + [item(c) for c in amendment_commitments]
    current = [i for i in items if i["document_effect"] == DocumentEffect.in_force.value]
    unreviewed = [i["id"] for i in items if i["review_status"] == "unreviewed" and i["needs_review"]]
    unreviewed += [f["id"] for f in findings if f["review_status"] == "unreviewed" and f["verdict"] != "consistent"
                   and f["severity"] != "info"]
    report = {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "tool": {"name": "ClaimTrace", "version": __version__},
        "disclaimer": DISCLAIMER,
        "document": {"id": doc.id, "title": doc.title, "version": doc.version_label, "type": doc.doc_type.value,
                     "checksum_sha256": doc.checksum_sha256, "text_sha256": doc.text_sha256,
                     "normalizer_version": doc.normalizer_version, "warnings": doc.warnings},
        "amendments": [{"id": d.id, "title": d.title, "version": d.version_label, "checksum_sha256": d.checksum_sha256}
                       for d in amendments],
        "summary": {"commitments_total": len(items), "commitments_current": len(current),
                    "needs_review": sum(1 for i in items if i["needs_review"]),
                    "findings": len(findings), "unreviewed_items": len(unreviewed),
                    "integrity_failures": len(integrity_failures)},
        "unreviewed_item_ids": unreviewed,
        "integrity_failures": integrity_failures,
        "commitments": items,
        "findings": findings,
        "answers": [{"id": a.id, "question": a.question, "status": a.status.value, "answer": a.answer_text,
                     "confidence": a.confidence.value, "review_status": store.current_review_status(a.id).value,
                     "citations": [c.span.model_dump(mode="json") for c in a.citations]} for a in answers],
        "review_trail": trail,
        "not_checked": NOT_CHECKED,
        "reviewer_identity_note": "Reviewer names are self-declared; v0.1 has no user accounts.",
    }
    body = json.dumps({k: v for k, v in report.items() if k != "generated_at"}, sort_keys=True, default=str)
    report["content_sha256"] = hashlib.sha256(body.encode()).hexdigest()
    return report


def _loc(i: dict) -> str:
    loc = i["location"]
    return f"{loc['document']} {loc['version']}, §{loc['section'] or '?'}" + (f", p.{loc['page']}" if loc["page"] else "")


def render_markdown(r: dict) -> str:
    out = [f"# ClaimTrace report: {r['document']['title']} ({r['document']['version']})", "",
           f"> {r['disclaimer']}", "",
           f"Generated {r['generated_at']} by ClaimTrace {r['tool']['version']} · document SHA-256 "
           f"`{r['document']['checksum_sha256']}` · report content hash `{r['content_sha256']}`", ""]
    s = r["summary"]
    out += ["## Summary", "",
            f"- Commitments: {s['commitments_current']} current of {s['commitments_total']} extracted",
            f"- Flagged for review: {s['needs_review']}",
            f"- Unreviewed items needing attention: **{s['unreviewed_items']}**",
            f"- Verification findings: {s['findings']}",
            f"- Quote integrity failures: {s['integrity_failures']}", ""]
    for w in r["document"]["warnings"]:
        out.append(f"> Warning: {w}")
    out += ["## Commitments", ""]
    for i in r["commitments"]:
        flag = " · NEEDS REVIEW" if i["needs_review"] else ""
        eff = "" if i["document_effect"] == "in_force" else f" · {i['document_effect'].upper()}"
        due = f" · due: {i['deadline'].get('date') or i['deadline'].get('raw')}" if i["deadline"] else ""
        out += [f"### §{i['section'] or '?'} {i['type']} ({i['obliging_party'] or 'no party named'}){eff}{flag}", "",
                f"> \"{i['quote']}\"", "", f"- Source: {_loc(i)}{due}",
                f"- Confidence: {i['confidence']} · review: {i['review_status']} · quote verified: {i['quote_verified']}"]
        out += [f"- Note: {c}" for c in i["caveats"]] + [f"- Review reason: {c}" for c in i["review_reasons"]] + [""]
    if r["findings"]:
        out += ["## Verification findings", "", "| Verdict | Severity | Subject | Explanation | Action | Review |",
                "|---|---|---|---|---|---|"]
        for f in r["findings"]:
            if f["verdict"] == "not_addressed" and f["mode"] == "amendment":
                continue
            cell = lambda t: str(t).replace("|", "\\|").replace("\n", " ")  # noqa: E731
            out.append(f"| {f['verdict']} | {f['severity']} | {cell(f['subject'][:120])} | {cell(f['explanation'])} | "
                       f"{cell(f['recommended_action'])} | {f['review_status']} |")
        out.append("")
    if r["review_trail"]:
        out += ["## Review trail", ""] + [f"- {t['at']} · {t['reviewer']} (self-declared) · {t['decision']} on "
                                         f"{t['target_kind']} {t['target_id']}" + (f": {t['note']}" if t["note"] else "")
                                         for t in r["review_trail"]] + [""]
    out += ["## What was not checked", ""] + [f"- {n}" for n in r["not_checked"]] + ["", f"_{r['disclaimer']}_", ""]
    return "\n".join(out)


def render_html(r: dict) -> str:
    """Print-ready HTML. Every value is escaped; the CSP forbids scripts and remote loads."""
    e = html.escape
    rows = []
    for i in r["commitments"]:
        cls = "superseded" if i["document_effect"] != "in_force" else ""
        rows.append(
            f"<article class='item {cls}'><h3>§{e(str(i['section'] or '?'))} · {e(i['type'])} · "
            f"{e(i['obliging_party'] or 'no party named')}"
            + (f" · <strong>{e(i['document_effect'].upper())}</strong>" if cls else "")
            + (" · <strong>Needs review</strong>" if i["needs_review"] else "")
            + f"</h3><blockquote>{e(i['quote'])}</blockquote><p class='meta'>{e(_loc(i))} · confidence "
            f"{e(i['confidence'])} · review {e(i['review_status'])} · quote verified {e(str(i['quote_verified']))}</p>"
            + "".join(f"<p class='note'>{e(c)}</p>" for c in i["caveats"] + i["review_reasons"]) + "</article>")
    frows = "".join(
        f"<tr><td>{e(f['verdict'])}</td><td>{e(f['severity'])}</td><td>{e(f['subject'])}</td>"
        f"<td>{e(f['explanation'])}</td><td>{e(f['recommended_action'])}</td><td>{e(f['review_status'])}</td></tr>"
        for f in r["findings"] if not (f["verdict"] == "not_addressed" and f["mode"] == "amendment"))
    trail = "".join(f"<li>{e(t['at'])} · {e(t['reviewer'])} (self-declared) · {e(t['decision'])} · "
                    f"{e(t['target_kind'])} {e(t['target_id'])}{(': ' + e(t['note'])) if t['note'] else ''}</li>"
                    for t in r["review_trail"])
    s = r["summary"]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>ClaimTrace report: {e(r['document']['title'])}</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;color:#111;max-width:60rem;margin:2rem auto;padding:0 1rem}}
blockquote{{margin:.25rem 0;padding:.5rem .75rem;border-left:4px solid #1d4ed8;background:#f1f5f9}}
.superseded blockquote{{border-color:#9ca3af;text-decoration:line-through;color:#4b5563}}
.meta,.note{{color:#374151;margin:.25rem 0}}.disclaimer{{border:2px solid #111;padding:.75rem}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #9ca3af;padding:.25rem .5rem;vertical-align:top}}
.item{{break-inside:avoid;margin-bottom:1rem}}@media print{{body{{margin:0}}}}</style></head><body>
<h1>ClaimTrace report: {e(r['document']['title'])} ({e(r['document']['version'])})</h1>
<p class="disclaimer"><strong>Not legal advice.</strong> {e(r['disclaimer'])}</p>
<p>Generated {e(r['generated_at'])} · ClaimTrace {e(r['tool']['version'])} · document SHA-256
<code>{e(r['document']['checksum_sha256'])}</code> · report hash <code>{e(r['content_sha256'])}</code></p>
<h2>Summary</h2><ul><li>Commitments: {s['commitments_current']} current of {s['commitments_total']}</li>
<li>Flagged for review: {s['needs_review']}</li><li><strong>Unreviewed items needing attention:
{s['unreviewed_items']}</strong></li><li>Quote integrity failures: {s['integrity_failures']}</li></ul>
{''.join(f'<p class="note">Warning: {e(w)}</p>' for w in r['document']['warnings'])}
<h2>Commitments</h2>{''.join(rows)}
<h2>Verification findings</h2><table><thead><tr><th>Verdict</th><th>Severity</th><th>Subject</th><th>Explanation</th>
<th>Recommended action</th><th>Review</th></tr></thead><tbody>{frows}</tbody></table>
<h2>Review trail</h2><ul>{trail or '<li>No review decisions recorded.</li>'}</ul>
<h2>What was not checked</h2><ul>{''.join(f'<li>{e(n)}</li>' for n in r['not_checked'])}</ul>
<p class="disclaimer">{e(r['disclaimer'])}</p></body></html>"""


def deadlines_csv(store: Store, doc_id: str) -> str:
    """Spreadsheet-friendly deadline list (opens in Excel). Cells are guarded against formula injection."""
    def safe(v: object) -> str:
        t = "" if v is None else str(v)
        return "'" + t if t[:1] in ("=", "+", "-", "@", "\t", "\r") else t

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "who", "for whom", "what", "due date", "timing (as written)", "status", "needs review",
                "quote", "document", "version"])
    amend_ids = [d.id for d in store.list_documents() if d.amends_document_id == doc_id]
    for c in store.objects(Commitment, doc_id) + [c for d in amend_ids for c in store.objects(Commitment, d)]:
        if not c.deadline:
            continue
        w.writerow([safe(x) for x in (c.section_number, c.obliging_party, c.beneficiary_party, c.action,
                                      c.deadline.date, c.deadline.raw, c.status.value, c.needs_review, c.text,
                                      c.provenance.span.document_title, c.provenance.span.document_version)])
    return buf.getvalue()


# ---------------------------------------------------------------- ICS (RFC 5545)
def ics_escape(text: str) -> str:
    """TEXT value escaping (RFC 5545 §3.3.11)."""
    return (text.replace("\\", "\\\\").replace(";", "\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n"))


def _fold(line: str) -> str:
    """Fold content lines at 75 octets without splitting a UTF-8 character (RFC 5545 §3.1)."""
    out: list[str] = []
    cur, size, limit = "", 0, 75
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > limit:
            out.append(cur)
            cur, size, limit = " ", 1, 75
        cur += ch
        size += n
    out.append(cur)
    return "\r\n".join(out)


def deadlines_ics(store: Store, doc_id: str, now: datetime | None = None) -> str:
    """Calendar of the in-force deadlines with a resolved date. Nothing is fetched or sent; the user downloads it."""
    from datetime import timedelta

    doc = store.get_document(doc_id)
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    amend_ids = [d.id for d in store.list_documents() if d.amends_document_id == doc_id]
    items = store.objects(Commitment, doc_id) + [c for d in amend_ids for c in store.objects(Commitment, d)]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//ClaimTrace//ClaimTrace {__version__}//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:" + ics_escape(f"Deadlines: {doc.title}")]
    for c in sorted(items, key=lambda c: (c.deadline.date.isoformat() if c.deadline and c.deadline.date else "", c.id)):
        if not c.deadline or c.deadline.date is None or c.document_effect != DocumentEffect.in_force:
            continue
        day = c.deadline.date
        who = c.obliging_party or "Unnamed party"
        span = c.provenance.span
        where = f"{span.document_title or doc.title} {span.document_version or ''} §{c.section_number or span.section or '?'}"
        desc = [f'"{c.text}"', f"Source: {where.strip()}", f"Timing as written: {c.deadline.raw or ''}"]
        if c.needs_review:
            desc.append("Flagged for review: " + "; ".join(c.review_reasons or ["see ClaimTrace"]))
        desc += [*c.caveats, "Check the quote before relying on this date. ClaimTrace is not legal advice."]
        lines += ["BEGIN:VEVENT", f"UID:{c.id}@claimtrace.local", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
                  "SUMMARY:" + ics_escape(f"{who}: {c.action}"[:200]), "DESCRIPTION:" + ics_escape("\n".join(desc)),
                  "TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "".join(_fold(x) + "\r\n" for x in lines)
