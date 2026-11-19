"""In-process engine facade for the browser build (Pyodide) and other single-process hosts.

The same ingestion, extraction, question-answering and verification code as the server, behind a small
JSON-in/JSON-out API, on an in-memory SQLite store. Differences from the server, all deliberate:

- Files are parsed in this process (``parsers.parse``), not in the sandboxed subprocess: Pyodide has no
  subprocesses, and the browser tab is itself the sandbox. The server path is unchanged.
- No language model and no network: rules only. Nothing in this module imports fastapi, uvicorn or httpx.
- No OCR: a scanned PDF is kept with the SCANNED warning, as on a server without Tesseract.

Use ``Session`` directly, or the module-level ``analyze``/``ask``/``verify``/``document``/``export``/``reset``
functions, which share one session. ``call(json)`` is the single entry point the web worker uses.
"""

from __future__ import annotations

import json
from typing import Any

from claimtrace import __version__
from claimtrace.core.models import (
    Commitment,
    DocType,
    Document,
    DocumentEffect,
    EdgeType,
    Party,
    Severity,
    Span,
)
from claimtrace.core.store import Store
from claimtrace.extraction import analyze_document, apply_amendments
from claimtrace.ingestion.parsers import IngestError, parse
from claimtrace.ingestion.pipeline import IngestOptions, check_upload, ingest_parsed
from claimtrace.verification import answer_question, verify_documents
from claimtrace.verification.report import DISCLAIMER, build_report, render_markdown

MAX_FILE_BYTES = 10 * 1024 * 1024  # the try page's cap; below the server's 20 MB
# The browser runs the engine on one thread, about 2-3x slower than CPython. Past these sizes a document is
# refused with a reason rather than left running for minutes (analysis time is linear in both).
MAX_TEXT_CHARS = 1_000_000  # roughly 400 pages
MAX_PASSAGES = 20_000
SEVERITY_ORDER = {Severity.high.value: 0, Severity.medium.value: 1, Severity.low.value: 2, Severity.info.value: 3}

__all__ = ["MAX_FILE_BYTES", "MAX_PASSAGES", "MAX_TEXT_CHARS", "Session", "analyze", "ask", "call", "document",
           "export", "reset", "verify"]


def _span_verified(store: Store, span: Span | None, texts: dict[str, str | None] | None = None) -> bool:
    """`texts` caches document text across calls: fetching it once per quote made the register quadratic."""
    if span is None:
        return False
    cache = texts if texts is not None else {}
    if span.document_id not in cache:
        try:
            cache[span.document_id] = store.get_document_text(span.document_id)
        except Exception:  # noqa: BLE001 - a span into a removed document does not verify
            cache[span.document_id] = None
    text = cache[span.document_id]
    return text is not None and text[span.char_start : span.char_end] == span.quote


def _span(store: Store, span: Span | None, texts: dict[str, str | None] | None = None) -> dict | None:
    if span is None:
        return None
    return {**span.model_dump(mode="json"), "verified": _span_verified(store, span, texts)}


class Session:
    """One workspace: an in-memory store holding the documents analysed so far."""

    def __init__(self) -> None:
        self.store = Store(":memory:")

    # ---- documents ------------------------------------------------------
    def analyze(self, files: list[dict]) -> dict:
        """Add files ({name, bytes}) and analyse them. Returns the whole register, not only the new files.

        A file that cannot be read is reported in ``warnings`` (code + plain message) and skipped; the
        others are still analysed. Amendments are stored after the documents they amend, whatever the
        order given, so "amends: <title>" links resolve within one call."""
        problems: list[dict] = []
        parsed: list[tuple[str, bytes, Any]] = []
        for f in files:
            name = str(f.get("name") or "document")
            data = f.get("bytes") or b""
            if not isinstance(data, bytes | bytearray):
                data = bytes(data)
            data = bytes(data)
            try:
                if len(data) > MAX_FILE_BYTES:
                    raise IngestError("file_too_large", f"Files must be under {MAX_FILE_BYTES // (1024 * 1024)} MB.")
                kind = check_upload(name, data)
                raw = parse(kind, data, _no_ocr)
                _check_size(raw)
            except IngestError as e:
                problems.append({"file": name, "code": e.code, "message": e.message})
                continue
            except MemoryError:
                problems.append({"file": name, "code": "resource_limit", "message": "The file was too large to read here."})
                continue
            except Exception:  # noqa: BLE001 - never echo parser internals (they may include document text)
                problems.append({"file": name, "code": "parse_failed", "message": "The file could not be read."})
                continue
            parsed.append((name, data, raw))
        # amendments last: their "amends" title is looked up among the documents already stored
        parsed.sort(key=lambda t: 1 if (t[2].amends or (t[2].doc_type or "").lower() == "amendment") else 0)
        new_ids: list[str] = []
        for name, data, raw in parsed:
            doc = ingest_parsed(self.store, name, data, raw, IngestOptions(sandbox=False, source="browser"))
            if doc.id not in new_ids:
                new_ids.append(doc.id)
        apply_amendments(self.store)
        for doc_id in new_ids:
            run = analyze_document(self.store, doc_id)
            if run.status != "done":
                d = self.store.get_document(doc_id)
                problems.append({"file": d.filename or d.title, "code": "analysis_failed",
                                 "message": "The file was read but could not be analysed."})
        out = self.register()
        out["warnings"] = problems + out["warnings"]
        out["added"] = new_ids
        return out

    def register(self) -> dict:
        """Every document, commitment, party and deadline in the workspace, with quote checks."""
        store = self.store
        docs = store.list_documents()
        titles = {d.id: d.title for d in docs}
        edges = [e for e in store.edges() if e.type == EdgeType.supersedes]
        commitments = store.objects(Commitment)
        by_id = {c.id: c for c in commitments}
        replaced_by: dict[str, list[str]] = {}
        for e in edges:  # src supersedes dst
            replaced_by.setdefault(e.dst_id, []).append(e.src_id)
        texts: dict[str, str | None] = {}
        ordinals = {p.id: p.ordinal for d in docs for p in store.passages(d.id)}
        items = [self._commitment(c, titles, [by_id[i] for i in replaced_by.get(c.id, []) if i in by_id], texts, ordinals)
                 for c in commitments]
        order = {d.id: n for n, d in enumerate(docs)}
        items.sort(key=lambda i: (order.get(i["document_id"], 0), i.pop("ordinal")))
        merged: dict[tuple[str, str | None], dict] = {}
        for p in store.objects(Party):  # one row per party, listing the documents that define it
            row = merged.setdefault((p.name, p.alias), {"name": p.name, "alias": p.alias, "documents": []})
            if titles.get(p.document_id) not in row["documents"]:
                row["documents"].append(titles.get(p.document_id))
        parties = list(merged.values())
        deadlines = [
            {"commitment_id": i["id"], "party": i["obliging_party"], "kind": i["deadline"]["kind"],
             "date": i["deadline"].get("date"), "raw": i["deadline"].get("raw"), "document": i["document"],
             "section": i["section"], "in_force": i["document_effect"] == DocumentEffect.in_force.value}
            for i in items if i["deadline"] and i["deadline"].get("kind") not in (None, "none")
        ]
        deadlines.sort(key=lambda d: (d["date"] is None, d["date"] or "", d["document"] or ""))
        warnings = [{"file": d.filename or d.title, "document_id": d.id, "code": w.split(":", 1)[0] if w[:1].isupper()
                     and ":" in w[:12] else "note", "message": w} for d in docs for w in d.warnings]
        return {
            "engine": {"name": "ClaimTrace", "version": __version__, "method": "rules", "network": False},
            "disclaimer": DISCLAIMER,
            "documents": [self._document(d, docs) for d in docs],
            "commitments": items,
            "parties": parties,
            "deadlines": deadlines,
            "warnings": warnings,
            "integrity": {"quotes": len(items), "verified": sum(1 for i in items if i["quote"]["verified"])},
        }

    def _document(self, d: Document, docs: list[Document]) -> dict:
        passages = self.store.passages(d.id)
        return {"id": d.id, "title": d.title, "version": d.version_label, "type": d.doc_type.value,
                "filename": d.filename, "pages": d.page_count, "passages": len(passages), "status": d.status,
                "amends_document_id": d.amends_document_id,
                "amended_by": [o.id for o in docs if o.amends_document_id == d.id],
                "is_evidence": d.doc_type in (DocType.audit_report, DocType.evidence, DocType.report),
                "warnings": d.warnings}

    def _commitment(self, c: Commitment, titles: dict[str, str], replacements: list[Commitment],
                    texts: dict[str, str | None], ordinals: dict[str, int]) -> dict:
        span = c.provenance.span
        ordinal = ordinals.get(span.passage_id, 0)
        return {
            "id": c.id, "document_id": c.document_id, "document": titles.get(c.document_id),
            "ordinal": ordinal,
            "section": c.section_number, "type": c.type.value, "modality": c.modality.value,
            "obliging_party": c.obliging_party, "beneficiary_party": c.beneficiary_party,
            "action": c.action, "text": c.text,
            "deadline": c.deadline.model_dump(mode="json") if c.deadline else None,
            "conditions": c.conditions, "exceptions": c.exceptions,
            "document_effect": c.document_effect.value, "status": c.status.value,
            "amends_section": c.amends_section,
            "replaced_by": [{"id": r.id, "document": titles.get(r.document_id), "section": r.section_number,
                             "text": r.text} for r in replacements],
            "confidence": c.confidence.value, "needs_review": c.needs_review,
            "review_reasons": c.review_reasons, "caveats": c.caveats,
            "quote": _span(self.store, span, texts),
        }

    def document(self, doc_id: str) -> dict:
        """The stored text of one document with its passages, for "show in document"."""
        d = self.store.get_document(doc_id)
        return {"id": d.id, "title": d.title, "version": d.version_label, "text": self.store.get_document_text(doc_id),
                "passages": [{"id": p.id, "section": p.section_number, "title": p.section_title, "page": p.page,
                              "char_start": p.char_start, "char_end": p.char_end} for p in self.store.passages(doc_id)]}

    # ---- questions and checks -------------------------------------------
    def ask(self, question: str, document_ids: list[str] | None = None) -> dict:
        ans = answer_question(self.store, question, document_ids or None)
        out = ans.model_dump(mode="json")
        for cit in out["citations"]:
            cit["span"]["verified"] = cit["verified"]
        return out

    def verify(self, base_id: str, other_id: str) -> dict:
        run = verify_documents(self.store, base_id, other_id)
        out = run.model_dump(mode="json")
        titles = {d.id: d.title for d in self.store.list_documents()}
        out["base_document"] = titles.get(run.base_document_id)
        out["other_document"] = titles.get(run.other_document_id)
        findings = []
        for f, fj in zip(run.findings, out["findings"], strict=True):
            fj["subject_span"] = _span(self.store, f.subject_span)
            fj["supporting"] = [_span(self.store, s) for s in f.supporting]
            fj["conflicting"] = [_span(self.store, s) for s in f.conflicting]
            # "not addressed" rows (a clause the amendment leaves alone, a commitment the evidence never
            # mentions) are listed after the findings, so the page can fold them away
            fj["routine"] = f.verdict.value == "not_addressed"
            findings.append(fj)
        findings.sort(key=lambda fj: (fj["routine"], SEVERITY_ORDER.get(fj["severity"], 9)))
        out["findings"] = findings
        return out

    # ---- export -----------------------------------------------------------
    def export(self, fmt: str = "json") -> str:
        """The audit report (claimtrace.report/v1) for each document that is not an amendment."""
        docs = [d for d in self.store.list_documents() if not (d.amends_document_id and d.doc_type == DocType.amendment)]
        reports = [build_report(self.store, d.id) for d in docs]
        if fmt in ("md", "markdown"):
            return "\n\n---\n\n".join(render_markdown(r) for r in reports) or "# ClaimTrace\n\nNo documents.\n"
        return json.dumps({"schema": "claimtrace.browser-export/v1", "tool": {"name": "ClaimTrace", "version": __version__},
                           "disclaimer": DISCLAIMER, "reports": reports}, indent=2, default=str)

    def reset(self) -> dict:
        self.store.conn.close()
        self.store = Store(":memory:")
        return self.register()


def _check_size(raw: Any) -> None:
    chars = sum(len(b.text) for b in raw.blocks)
    if chars > MAX_TEXT_CHARS:
        raise IngestError("too_long_for_browser",
                          f"This document has about {chars // 1000:,} thousand characters of text; the browser "
                          f"version reads up to {MAX_TEXT_CHARS // 1000:,} thousand. Try a smaller file, or "
                          "install ClaimTrace to read it on your computer.")
    passages = sum(1 for b in raw.blocks if b.text.strip())
    if passages > MAX_PASSAGES:
        raise IngestError("too_many_passages_for_browser",
                          f"This document has {passages:,} paragraphs; the browser version reads up to "
                          f"{MAX_PASSAGES:,}. Try a smaller file, or install ClaimTrace to read it on your computer.")


def _no_ocr(_data: bytes, _pages: list[int]) -> dict[int, tuple[str, float]]:
    """No OCR engine in the browser: pages without a text layer stay unread (SCANNED warning)."""
    return {}


_session: Session | None = None


def _s() -> Session:
    global _session
    if _session is None:
        _session = Session()
    return _session


def analyze(files: list[dict]) -> dict:
    return _s().analyze(files)


def ask(question: str, document_ids: list[str] | None = None) -> dict:
    return _s().ask(question, document_ids)


def verify(base_id: str, other_id: str) -> dict:
    return _s().verify(base_id, other_id)


def document(doc_id: str) -> dict:
    return _s().document(doc_id)


def export(fmt: str = "json") -> str:
    return _s().export(fmt)


def reset() -> dict:
    return _s().reset()


def call(request: str, files: list[dict] | None = None) -> str:
    """JSON-in/JSON-out dispatcher for the web worker: {"op": ..., ...args} -> {"ok": true, "result": ...}
    or {"ok": false, "error": {"code", "message"}}. File bytes travel separately (``files``) so they are
    not copied through JSON."""
    try:
        req = json.loads(request)
        op = req.get("op")
        if op == "analyze":
            result: Any = analyze(files or [])
        elif op == "register":
            result = _s().register()
        elif op == "ask":
            result = ask(str(req.get("question", "")), req.get("document_ids"))
        elif op == "verify":
            result = verify(str(req["base_id"]), str(req["other_id"]))
        elif op == "document":
            result = document(str(req["doc_id"]))
        elif op == "export":
            result = export(str(req.get("format", "json")))
        elif op == "reset":
            result = reset()
        else:
            return json.dumps({"ok": False, "error": {"code": "unknown_op", "message": f"Unknown operation {op!r}."}})
        return json.dumps({"ok": True, "result": result}, default=str)
    except IngestError as e:
        return json.dumps({"ok": False, "error": {"code": e.code, "message": e.message}})
    except Exception as e:  # noqa: BLE001 - report the kind of failure, never document text
        return json.dumps({"ok": False, "error": {"code": type(e).__name__, "message": "Something went wrong in the engine."}})
