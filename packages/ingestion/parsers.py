"""File-type checks and parsers. Runs inside the sandbox worker (see sandbox.py).

Every parser returns RawDoc: ordered text blocks with page numbers and heading flags.
Nothing here renders, executes, or follows links in the document.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import asdict, dataclass, field


class IngestError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Block:
    text: str
    page: int | None = None
    heading: bool = False


@dataclass
class RawDoc:
    blocks: list[Block]
    title: str | None = None
    author: str | None = None
    version: str | None = None
    doc_type: str | None = None
    amends: str | None = None
    page_count: int | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


MAX_DOCX_UNCOMPRESSED = 50 * 1024 * 1024
MAX_ZIP_RATIO = 100
MAX_PDF_PAGES = 500


def detect_kind(filename: str, data: bytes) -> str:
    """Allowlist by extension AND magic bytes; a mismatch is rejected."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf":
        if not data.startswith(b"%PDF-"):
            raise IngestError("type_mismatch", "File has a .pdf name but is not a PDF.")
        return "pdf"
    if ext == "docx":
        if not data.startswith(b"PK\x03\x04"):
            raise IngestError("type_mismatch", "File has a .docx name but is not a DOCX (zip) file.")
        return "docx"
    if ext in ("md", "markdown", "txt", "text"):
        if b"\x00" in data[:4096]:
            raise IngestError("type_mismatch", "Text file contains binary data.")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise IngestError("bad_encoding", "Text files must be UTF-8.") from e
        return "md" if ext in ("md", "markdown") else "txt"
    raise IngestError("unsupported_file_type", "Supported types: PDF, DOCX, Markdown (.md), plain text (.txt).")


# ---------------------------------------------------------------- markdown / text
_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def parse_text(data: bytes, markdown: bool) -> RawDoc:
    text = data.decode("utf-8")
    meta: dict[str, str] = {}
    m = _FRONT.match(text)
    if markdown and m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip().strip('"')
        text = text[m.end() :]
    blocks: list[Block] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        # markdown lists / headings inside one paragraph become separate blocks
        for line_group in _split_md_lines(para) if markdown else [para]:
            is_heading = markdown and line_group.startswith("#")
            clean = line_group.lstrip("#").strip() if is_heading else line_group
            if clean:
                blocks.append(Block(text=clean, page=1 if not markdown else None, heading=is_heading))
    title = meta.get("title")
    if not title:
        first_heading = next((b.text for b in blocks if b.heading), None)
        title = first_heading
    return RawDoc(
        blocks=blocks,
        title=title,
        author=meta.get("author"),
        version=meta.get("version"),
        doc_type=meta.get("doc_type"),
        amends=meta.get("amends"),
        page_count=None,
    )


def _split_md_lines(para: str) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    for line in para.splitlines():
        if line.lstrip().startswith("#") or re.match(r"^\s*(?:[-*]|\(?[a-z]\)|\(?[ivx]+\))\s+", line):
            if cur:
                out.append(" ".join(cur))
            cur = [line.strip()]
            if line.lstrip().startswith("#"):
                out.append(" ".join(cur))
                cur = []
        else:
            cur.append(line.strip())
    if cur:
        out.append(" ".join(cur))
    return out


# ---------------------------------------------------------------- docx
_BAD_DOCX_PARTS = ("vbaproject.bin", "oleobject", "activex", "embeddings/")
_BAD_EXTERNAL_RELS = ("attachedtemplate", "oleobject", "frame", "subdocument", "externallinkpath")


def check_docx_container(data: bytes) -> None:
    from defusedxml import ElementTree as DET
    from defusedxml.common import DefusedXmlException

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise IngestError("corrupt_file", "DOCX file is not a valid zip archive.") from e
    total = 0
    for info in zf.infolist():
        name = info.filename.lower()
        if any(b in name for b in _BAD_DOCX_PARTS):
            raise IngestError("unsafe_content", "DOCX contains macros, embedded objects or ActiveX; rejected.")
        if name.endswith((".zip", ".docx", ".xlsx", ".pptx")):
            raise IngestError("unsafe_content", "DOCX contains a nested archive; rejected.")
        total += info.file_size
        if info.compress_size and info.file_size / max(info.compress_size, 1) > MAX_ZIP_RATIO and info.file_size > 1_000_000:
            raise IngestError("unsafe_content", "DOCX compression ratio is suspicious (possible zip bomb).")
        if total > MAX_DOCX_UNCOMPRESSED:
            raise IngestError("file_too_large", "DOCX expands beyond the allowed size.")
    for info in zf.infolist():
        name = info.filename.lower()
        if not (name.endswith(".xml") or name.endswith(".rels")):
            continue
        raw = zf.read(info)
        try:
            root = DET.fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
        except DefusedXmlException as e:
            raise IngestError("unsafe_content", "DOCX contains XML entity/DTD declarations; rejected.") from e
        except Exception as e:  # noqa: BLE001 - any XML failure means corrupt input
            raise IngestError("corrupt_file", "DOCX contains malformed XML.") from e
        if name.endswith(".rels"):
            for rel in root:
                if rel.get("TargetMode", "").lower() == "external":
                    rtype = rel.get("Type", "").lower()
                    if any(b in rtype for b in _BAD_EXTERNAL_RELS):
                        raise IngestError("unsafe_content", "DOCX references external templates or objects; rejected.")


def parse_docx(data: bytes) -> RawDoc:
    check_docx_container(data)
    import docx  # python-docx; parser is configured with resolve_entities=False

    d = docx.Document(io.BytesIO(data))
    blocks: list[Block] = []
    warnings: list[str] = []
    numbered = False
    for p in d.paragraphs:
        t = p.text.strip()
        if not t:
            continue
        style = (p.style.name or "").lower() if p.style is not None else ""
        if p._p.pPr is not None and p._p.pPr.numPr is not None:
            numbered = True
        blocks.append(Block(text=t, heading=style.startswith("heading") or style == "title"))
    for table in d.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                blocks.append(Block(text=" | ".join(dict.fromkeys(cells))))
    if numbered:
        warnings.append(
            "This DOCX uses automatic numbering, which is not visible in extracted text; clause numbers may be missing."
        )
    warnings.append("DOCX files have no fixed pages; page numbers are not available.")
    cp = d.core_properties
    return RawDoc(blocks=blocks, title=cp.title or None, author=cp.author or None, warnings=warnings)


# ---------------------------------------------------------------- pdf
_PDF_DANGEROUS = (b"/JavaScript", b"/JS ", b"/JS(", b"/Launch", b"/EmbeddedFile", b"/RichMedia", b"/XFA")


def parse_pdf(data: bytes) -> RawDoc:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    for marker in _PDF_DANGEROUS:
        if marker in data:
            raise IngestError(
                "unsafe_content", "PDF contains active content (JavaScript, launch actions, embedded files or forms); rejected."
            )
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
    except (PdfReadError, ValueError) as e:
        raise IngestError("corrupt_file", "PDF could not be read.") from e
    if reader.is_encrypted:
        raise IngestError("encrypted_pdf", "PDF is encrypted or password-protected; remove protection first.")
    root = reader.trailer.get("/Root", {})
    names = root.get("/Names", {}) if hasattr(root, "get") else {}
    if hasattr(names, "get") and (names.get("/JavaScript") or names.get("/EmbeddedFiles")):
        raise IngestError("unsafe_content", "PDF contains JavaScript or embedded files; rejected.")
    n = len(reader.pages)
    if n > MAX_PDF_PAGES:
        raise IngestError("too_many_pages", f"PDF has {n} pages; the limit is {MAX_PDF_PAGES}.")
    blocks: list[Block] = []
    chars = 0
    for i, page in enumerate(reader.pages, start=1):
        txt = page.extract_text() or ""
        chars += len(txt.strip())
        for para in _pdf_paragraphs(txt):
            blocks.append(Block(text=para, page=i, heading=_looks_like_heading(para)))
    warnings: list[str] = []
    if chars < 40 * max(n, 1):
        warnings.append(
            "SCANNED: This PDF has little or no text layer (it may be a scanned image). "
            "ClaimTrace v0.1 cannot read images, so results will be incomplete or empty."
        )
    meta = reader.metadata
    return RawDoc(
        blocks=blocks,
        title=(meta.title if meta else None) or None,
        author=(meta.author if meta else None) or None,
        page_count=n,
        warnings=warnings,
    )


_CLAUSE_START = re.compile(r"^(?:\d+(?:\.\d+)*\.?|\([a-z]{1,3}\)|[a-z]\)|Schedule\s+\w+|Article\s+\w+)\s")


def _looks_like_heading(line: str) -> bool:
    return (
        len(line) < 80
        and not line.rstrip().endswith((".", ",", ";", ":"))
        and (re.match(r"^\d+\.?\s+[A-Z]", line) is not None or line.isupper())
    )


def _pdf_paragraphs(txt: str) -> list[str]:
    """Rebuild paragraphs from PDF lines: start a new one at clause numbers, headings or blank lines."""
    paras: list[str] = []
    cur: list[str] = []
    for line in txt.splitlines():
        s = line.strip()
        if not s:
            if cur:
                paras.append(" ".join(cur))
                cur = []
            continue
        if cur and (_CLAUSE_START.match(s) or _looks_like_heading(s) or _looks_like_heading(cur[-1])):
            paras.append(" ".join(cur))
            cur = []
        cur.append(s)
    if cur:
        paras.append(" ".join(cur))
    return paras


def parse(kind: str, data: bytes) -> RawDoc:
    if kind == "pdf":
        return parse_pdf(data)
    if kind == "docx":
        return parse_docx(data)
    return parse_text(data, markdown=(kind == "md"))
