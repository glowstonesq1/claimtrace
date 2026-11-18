"""Turn parsed blocks into a stored Document with offset-exact passages."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from claimtrace.core.models import DocType, Document, Passage
from claimtrace.core.store import Store
from claimtrace.core.text import NORMALIZER_VERSION, normalize, sha256_bytes, sha256_text

from .ocr import OcrFunc
from .parsers import IngestError, RawDoc, detect_kind
from .sandbox import parse_sandboxed

MAX_UPLOAD_BYTES = 20 * 1024 * 1024

_NUM = re.compile(r"^(?P<num>(?:\d+(?:\.\d+)*\.?|[A-Z]\.\d+(?:\.\d+)*|\([a-z]{1,3}\)|[a-z]\)))\s+")
_HEADING_NUM = re.compile(r"^(?:(?:Section|Clause|Article)\s+)?(\d+(?:\.\d+)*|[A-Z])\.?\s+(.+)$")
_SCHEDULE_HEADING = re.compile(r"^(Schedule|Annex|Appendix|Exhibit)\s+(\d+|[A-Z])\b[.:]?(?:\s*[-:]?\s*(.*))?$", re.I)


@dataclass
class IngestOptions:
    title: str | None = None
    version_label: str | None = None
    doc_type: str | None = None
    author: str | None = None
    source: str = "upload"
    amends_document_id: str | None = None
    tags: list[str] | None = None
    allow_external_llm: bool = False
    sandbox: bool = True
    ocr: OcrFunc | None = None  # None: the installed engine (ocr.default_ocr); in the sandbox it must be importable


def segment(raw: RawDoc, doc_id: str) -> tuple[str, list[Passage]]:
    """Normalise each block and lay them out in one text with exact offsets."""
    parts: list[str] = []
    passages: list[Passage] = []
    offset = 0
    section_title: str | None = None
    heading_num: str | None = None
    parent_num: str | None = None
    schedule: str | None = None  # "Schedule 2": numbers inside it become "Schedule 2/1.1"
    for block in raw.blocks:
        text = normalize(block.text)
        if not text:
            continue
        sm = _SCHEDULE_HEADING.match(text)
        if sm and (block.heading or (len(text) < 90 and not text.endswith((".", ";", ",")))):
            schedule = f"{sm.group(1).title()} {sm.group(2).upper() if sm.group(2).isalpha() else sm.group(2)}"
            heading_num, section_title = schedule, (sm.group(3) or "").strip(" -:.") or text
            parent_num = heading_num
            number: str | None = heading_num
        elif block.locator:  # a table row belongs to the clause it appears in
            number = parent_num or heading_num
        elif block.heading:
            m = _HEADING_NUM.match(text)
            heading_num, section_title = (m.group(1), m.group(2)) if m else (None, text)
            if schedule and heading_num:  # schedules come last: a numbered heading stays inside it
                heading_num = f"{schedule}/{heading_num}"
            parent_num = heading_num if (m or not schedule) else schedule
            number = heading_num if m else parent_num
        else:
            m = _NUM.match(text)
            if m:
                raw_num = m.group("num").rstrip(".")
                if raw_num.startswith("(") or raw_num.endswith(")"):
                    number = f"{parent_num}{raw_num if raw_num.startswith('(') else '(' + raw_num}" if parent_num else raw_num
                else:
                    number = f"{schedule}/{raw_num}" if schedule else raw_num
                    parent_num = number
            else:
                number = parent_num or heading_num
        if parts:
            offset += 2  # "\n\n" separator
        start = offset
        parts.append(text)
        offset += len(text)
        passages.append(
            Passage(
                id=f"psg_{doc_id[4:]}_{len(passages):04d}",
                document_id=doc_id,
                ordinal=len(passages),
                page=block.page,
                section_number=number,
                section_title=section_title,
                char_start=start,
                char_end=offset,
                text=text,
                hidden_text=block.hidden,
                ocr_confidence=block.ocr_confidence,
                locator=block.locator,
            )
        )
    return "\n\n".join(parts), passages


def _doc_type(value: str | None, filename: str) -> DocType:
    if value:
        v = value.strip().lower().replace(" ", "_")
        if v in DocType.__members__:
            return DocType(v)
    name = filename.lower()
    for key, dt in (
        ("amend", DocType.amendment),
        ("audit", DocType.audit_report),
        ("policy", DocType.policy),
        ("sow", DocType.sow),
        ("proposal", DocType.proposal),
        ("record", DocType.evidence),
        ("evidence", DocType.evidence),
        ("report", DocType.report),
        ("agreement", DocType.contract),
        ("contract", DocType.contract),
        ("msa", DocType.contract),
    ):
        if key in name:
            return dt
    return DocType.other


def ingest_bytes(store: Store, filename: str, data: bytes, opts: IngestOptions | None = None) -> Document:
    opts = opts or IngestOptions()
    if len(data) > MAX_UPLOAD_BYTES:
        raise IngestError("file_too_large", f"Files must be under {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if not data:
        raise IngestError("empty_file", "The file is empty.")
    kind = detect_kind(filename, data)
    checksum = sha256_bytes(data)
    existing = store.find_by_checksum(checksum)
    if existing:
        return existing
    if opts.sandbox:
        raw = parse_sandboxed(kind, data, opts.ocr)
    else:
        from .parsers import parse

        raw = parse(kind, data, opts.ocr)
    doc_id = "doc_" + uuid.uuid4().hex[:12]
    text, passages = segment(raw, doc_id)
    warnings = list(raw.warnings)
    from claimtrace.core.text import looks_like_injection

    suspicious = [p.section_number or str(p.ordinal) for p in passages if looks_like_injection(p.text)]
    if suspicious:
        warnings.append("INJECTION: Some passages contain instruction-like text aimed at AI tools (sections: "
                        + ", ".join(suspicious[:10]) + "). Items from them are flagged for review.")
    hidden = [p.section_number or str(p.ordinal) for p in passages if p.hidden_text]
    if hidden:
        warnings.append("HIDDEN: Some passages contain text a reader would not see (white, tiny, off-page or hidden "
                        "formatting) (sections: " + ", ".join(hidden[:10]) + "). Items from them are flagged for "
                        "review and they are never sent to a language model.")
    if not passages:
        warnings.append("SCANNED: No readable text was found in this file. Nothing was analysed.")
    amends_id = opts.amends_document_id
    if not amends_id and raw.amends:
        target = next((d for d in store.list_documents() if d.title.strip().lower() == raw.amends.strip().lower()), None)
        amends_id = target.id if target else None
        if not target:
            warnings.append(f"This document says it amends '{raw.amends}', which has not been uploaded yet.")
    safe_name = re.sub(r"[^\w.\- ]", "_", filename)[-120:]
    doc = Document(
        id=doc_id,
        title=(opts.title or raw.title or safe_name).strip()[:300],
        version_label=opts.version_label or raw.version or "v1",
        doc_type=_doc_type(opts.doc_type or raw.doc_type, safe_name),
        source=opts.source,
        author=opts.author or raw.author,
        filename=safe_name,
        checksum_sha256=checksum,
        text_sha256=sha256_text(text),
        normalizer_version=NORMALIZER_VERSION,
        page_count=raw.page_count,
        status="parsed",
        warnings=warnings,
        tags=opts.tags or [],
        amends_document_id=amends_id,
        allow_external_llm=opts.allow_external_llm,
    )
    store.add_document(doc, text, passages)
    return doc


def ingest_file(store: Store, path: str, opts: IngestOptions | None = None) -> Document:
    with open(path, "rb") as fh:
        data = fh.read(MAX_UPLOAD_BYTES + 1)
    return ingest_bytes(store, path.rsplit("/", 1)[-1], data, opts)


__all__ = ["IngestError", "IngestOptions", "ingest_bytes", "ingest_file", "segment"]
