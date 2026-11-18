"""File-type checks and parsers. Runs inside the sandbox worker (see sandbox.py).

Every parser returns RawDoc: ordered text blocks with page numbers and heading flags.
Nothing here renders, executes, or follows links in the document.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import asdict, dataclass, field

from claimtrace.core.models import OCR_LOW_CONFIDENCE

from .ocr import OcrFunc, default_ocr


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
    hidden: str | None = None  # why some of this text is not visible to a reader (white, tiny, off-page, w:vanish)
    locator: str | None = None  # e.g. "table 1, row 3" for DOCX table rows
    ocr_confidence: float | None = None  # 0-100 when the text came from OCR


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
        # headings, list items and numbered clauses on their own lines become separate blocks
        for line_group in _split_md_lines(para, markdown):
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


_LINE_START = re.compile(
    r"^\s*(?:[-*]\s+|\(?[a-z]{1,3}\)\s+|\(?[ivx]+\)\s+|\d+(?:\.\d+)*\.?\s+(?=\S)|"
    r"(?:clause|section|article|schedule)\s+\d+(?:\.\d+)*\.?\s+(?=[A-Z]))", re.I)


def _split_md_lines(para: str, markdown: bool = True) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    for line in para.splitlines():
        heading = markdown and line.lstrip().startswith("#")
        if heading or _LINE_START.match(line):
            if cur:
                out.append(" ".join(cur))
            cur = [line.strip()]
            if heading:
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
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(io.BytesIO(data))
    blocks: list[Block] = []
    warnings: list[str] = []
    numbered = False
    n_tables = 0
    styles = _DocxStyles(d.styles.element)
    for el in d.element.body.iterchildren():
        if el.tag == _W + "p":
            p = Paragraph(el, d)
            t = p.text.strip()
            if not t:
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            if p._p.pPr is not None and p._p.pPr.numPr is not None:
                numbered = True
            blocks.append(Block(text=t, heading=style.startswith("heading") or style == "title", hidden=_docx_hidden(p, styles)))
        elif el.tag == _W + "tbl":
            n_tables += 1
            blocks.extend(_docx_table_rows(Table(el, d), n_tables, styles))
    if numbered:
        warnings.append(
            "This DOCX uses automatic numbering, which is not visible in extracted text; clause numbers may be missing."
        )
    warnings.append("DOCX files have no fixed pages; page numbers are not available.")
    cp = d.core_properties
    return RawDoc(blocks=blocks, title=cp.title or None, author=cp.author or None, warnings=warnings)


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _on(el: object) -> bool:
    """A w:vanish / w:specVanish toggle is on unless w:val says false/0/off."""
    val = el.get(_W + "val")  # type: ignore[attr-defined]
    return val is None or val.lower() not in ("0", "false", "off")


# A colour is "near-white" when every channel is at least this bright (FFFFFE, F4F6F5, ...).
_NEAR_WHITE_CHANNEL = 0xF0
_WHITE_THEME_COLOURS = ("background1", "light1")


def _near_white_hex(val: str) -> bool:
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", val):
        return False  # "auto" and malformed values are not white
    return all(int(val[i : i + 2], 16) >= _NEAR_WHITE_CHANNEL for i in (0, 2, 4))


class _DocxStyles:
    """Run properties inherited from styles.xml: character style (w:rStyle), paragraph style (w:pStyle),
    each with its w:basedOn chain, then the document defaults. Direct run properties win over all of them."""

    _MAX_DEPTH = 16

    def __init__(self, styles_el: object) -> None:
        self._by_id: dict[str, object] = {}
        for st in styles_el.iter(_W + "style"):  # type: ignore[attr-defined]
            sid = st.get(_W + "styleId")
            if sid:
                self._by_id.setdefault(sid, st)
        dflt = styles_el.find(f"{_W}docDefaults/{_W}rPrDefault/{_W}rPr")  # type: ignore[attr-defined]
        self._defaults = [dflt] if dflt is not None else []

    def _chain(self, style_id: str | None) -> list[object]:
        out: list[object] = []
        seen: set[str] = set()
        while style_id and style_id not in seen and len(seen) < self._MAX_DEPTH:
            seen.add(style_id)
            st = self._by_id.get(style_id)
            if st is None:
                break
            rpr = st.find(_W + "rPr")  # type: ignore[attr-defined]
            if rpr is not None:
                out.append(rpr)
            based = st.find(_W + "basedOn")  # type: ignore[attr-defined]
            style_id = based.get(_W + "val") if based is not None else None
        return out

    def run_props(self, r: object, ppr: object | None) -> list[object]:
        """rPr elements that apply to run `r`, most specific first."""
        out: list[object] = []
        rpr = r.find(_W + "rPr")  # type: ignore[attr-defined]
        if rpr is not None:
            out.append(rpr)
            rstyle = rpr.find(_W + "rStyle")
            if rstyle is not None:
                out += self._chain(rstyle.get(_W + "val"))
        if ppr is not None:
            pstyle = ppr.find(_W + "pStyle")  # type: ignore[attr-defined]
            out += self._chain(pstyle.get(_W + "val") if pstyle is not None else "Normal")
        else:
            out += self._chain("Normal")
        return out + self._defaults


def _first(props: list[object], *tags: str) -> object | None:
    for rpr in props:
        for tag in tags:
            el = rpr.find(_W + tag)  # type: ignore[attr-defined]
            if el is not None:
                return el
    return None


def _docx_hidden(p: object, styles: _DocxStyles | None = None) -> str | None:
    """Reason a paragraph contains text Word does not display, or None.

    Properties are resolved as Word does: direct run formatting, then the run's character style, then the
    paragraph style (each following w:basedOn), then document defaults.
    """
    reasons: list[str] = []
    ppr = p._p.pPr  # type: ignore[attr-defined]
    for r in p._p.iter(_W + "r"):  # type: ignore[attr-defined]
        text = "".join(t.text or "" for t in r.iter(_W + "t")).strip()
        if not text:
            continue
        props = styles.run_props(r, ppr) if styles is not None else [x for x in [r.find(_W + "rPr")] if x is not None]
        vanish = _first(props, "vanish", "specVanish")
        if vanish is not None and _on(vanish):
            reasons.append("hidden (w:vanish) text")
        color = _first(props, "color")
        if color is not None and (
            _near_white_hex(color.get(_W + "val") or "")  # type: ignore[attr-defined]
            or (color.get(_W + "themeColor") or "") in _WHITE_THEME_COLOURS  # type: ignore[attr-defined]
        ):
            reasons.append("white text")
        sz = _first(props, "sz")
        val = (sz.get(_W + "val") or "") if sz is not None else ""  # type: ignore[attr-defined]
        if val.isdigit() and int(val) < 4:  # half-points
            reasons.append("tiny text (under 2 pt)")
    return "; ".join(dict.fromkeys(reasons)) or None


TABLE_CELL_SEP = " | "


def _docx_table_rows(table: object, n: int, styles: _DocxStyles | None = None) -> list[Block]:
    """One block per row: non-empty cells joined with " | " (merged cells once), with a "table N, row M" locator."""
    out: list[Block] = []
    for r, row in enumerate(table.rows, start=1):  # type: ignore[attr-defined]
        seen: set[int] = set()
        cells: list[str] = []
        hidden: list[str] = []
        for cell in row.cells:
            if id(cell._tc) in seen:
                continue
            seen.add(id(cell._tc))
            text = " ".join(x.strip() for x in cell.text.split("\n") if x.strip())
            if text:
                cells.append(text.replace(TABLE_CELL_SEP, " / "))
            hidden += [h for para in cell.paragraphs if (h := _docx_hidden(para, styles))]
        if cells:
            out.append(Block(text=TABLE_CELL_SEP.join(cells), locator=f"table {n}, row {r}",
                             hidden="; ".join(dict.fromkeys(hidden)) or None))
    return out


# ---------------------------------------------------------------- pdf
_HIDDEN_FONT_PT = 2.0
_NEAR_WHITE = 0.95


def _gray_of(op: bytes, args: list) -> float | None:
    """Lowest channel of a fill colour as 0..1 lightness, or None if unknown (patterns, spot colours)."""
    try:
        vals = [float(a) for a in args]
    except (TypeError, ValueError):
        return None
    if op == b"g" or (op in (b"sc", b"scn") and len(vals) == 1):
        return vals[0]
    if op == b"rg" or (op in (b"sc", b"scn") and len(vals) == 3):
        return min(vals)
    if op == b"k" or (op in (b"sc", b"scn") and len(vals) == 4):
        c, m, y, k = vals
        return min((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None


def _mult(m: list[float], n: list[float]) -> list[float]:
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return [a * a2 + b * c2, a * b2 + b * d2, c * a2 + d * c2, c * b2 + d * d2, e * a2 + f * c2 + e2, e * b2 + f * d2 + f2]


def _group_hidden(pieces: list[tuple[str, str, float] | None]) -> list[tuple[str, str]]:
    """Join hidden fragments that are drawn consecutively (no visible text between them), so text split
    into short pieces ("2.2 T", "he Cu", ...) is judged as a whole. Each run is returned both whole and
    split per line (same baseline), since a run can straddle paragraphs."""
    out: list[tuple[str, str]] = []
    run: list[tuple[str, str, float]] = []

    def flush() -> None:
        if not run:
            return
        out.append(("".join(t for t, _, _ in run), "; ".join(dict.fromkeys(r for _, r, _ in run))))
        line: list[tuple[str, str, float]] = []
        for piece in run + [("", "", float("nan"))]:
            if line and not abs(piece[2] - line[-1][2]) <= 1.0:
                if len(line) < len(run):
                    out.append(("".join(t for t, _, _ in line), "; ".join(dict.fromkeys(r for _, r, _ in line))))
                line = []
            line.append(piece)
        run.clear()

    for piece in pieces:
        if piece is None:
            flush()
        else:
            run.append(piece)
    flush()
    return out


def _pdf_page_text(page: object) -> tuple[str, list[tuple[str, str]]]:
    """Extract a page's text and the (aggregated) fragments a reader would not see, with the reason."""
    box = page.mediabox  # type: ignore[attr-defined]
    x0, y0, x1, y1 = (float(v) for v in (box.left, box.bottom, box.right, box.top))
    state = {"fill": 0.0, "tr": 0.0}
    stack: list[dict[str, float]] = []
    pieces: list[tuple[str, str, float] | None] = []  # None: visible text, which ends a hidden run

    def before(op: bytes, args: list, cm: list, tm: list) -> None:
        if op == b"q":
            stack.append(dict(state))
        elif op == b"Q" and stack:
            state.update(stack.pop())
        elif op in (b"g", b"rg", b"k", b"sc", b"scn"):
            g = _gray_of(op, args)
            if g is not None:
                state["fill"] = g
        elif op == b"Tr" and args:
            try:
                state["tr"] = float(args[0])
            except (TypeError, ValueError):
                pass

    def visit(text: str, cm: list, tm: list, font: object, size: float) -> None:
        if not text.strip():
            return
        m = _mult([float(v) for v in tm], [float(v) for v in cm])
        scale = (m[2] ** 2 + m[3] ** 2) ** 0.5 or 1.0
        reasons = []
        if state["tr"] == 3:
            reasons.append("invisible (render mode 3) text")
        if state["fill"] >= _NEAR_WHITE:
            reasons.append("white or near-white text")
        if 0 < float(size or 0) * scale < _HIDDEN_FONT_PT:
            reasons.append("tiny text (under 2 pt)")
        x, y = m[4], m[5]
        if x < x0 - 5 or x > x1 + 5 or y < y0 - 5 or y > y1 + 5:
            reasons.append("text placed off the page")
        pieces.append((text, "; ".join(reasons), y) if reasons else None)

    txt = page.extract_text(visitor_operand_before=before, visitor_text=visit) or ""  # type: ignore[attr-defined]
    return txt, _group_hidden(pieces)


_MIN_HIDDEN_CHARS = 6  # shorter hidden runs (a stray white bullet or space) match almost any paragraph


def _squeeze(t: str) -> str:
    return re.sub(r"\s+", "", t).lower()


def _overlaps(flat: str, run: str) -> bool:
    """`run` occurs in `flat`, `flat` lies inside `run`, or one straddles the other's edge by at least
    _MIN_HIDDEN_CHARS characters (a hidden run is often split across extracted paragraphs)."""
    if run in flat or (flat and flat in run):
        return True
    k = _MIN_HIDDEN_CHARS
    # run starts inside flat and continues past its end
    i = flat.find(run[:k], max(0, len(flat) - len(run)))
    while i >= 0:
        if run.startswith(flat[i:]):
            return True
        i = flat.find(run[:k], i + 1)
    # run starts before flat and ends inside it
    j = run.find(flat[:k], max(0, len(run) - len(flat)))
    while j >= 0:
        if flat.startswith(run[j:]):
            return True
        j = run.find(flat[:k], j + 1)
    return False


def _hidden_reason(para: str, hidden: list[tuple[str, str]]) -> str | None:
    """Reasons for hidden runs that overlap `para`. Whitespace is ignored on both sides, because text
    extraction re-spaces split fragments ("2.2 T\nhe Cu" for "2.2 The Cu")."""
    flat = _squeeze(para)
    reasons = [r for t, r in hidden if len(sq := _squeeze(t)) >= _MIN_HIDDEN_CHARS and _overlaps(flat, sq)]
    return "; ".join(dict.fromkeys(reasons)) or None

_PDF_DANGEROUS = (b"/JavaScript", b"/JS ", b"/JS(", b"/Launch", b"/EmbeddedFile", b"/RichMedia", b"/XFA")


def parse_pdf(data: bytes, ocr: OcrFunc | None = None) -> RawDoc:
    """`ocr` reads pages without a text layer; None means the installed engine, if any (see ocr.py)."""
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
    warnings: list[str] = []
    pages = [_pdf_page_text(page) for page in reader.pages]
    thin = [i for i, (txt, _) in enumerate(pages, start=1) if len(txt.strip()) < 40]
    engine = ocr if ocr is not None else default_ocr()
    read: dict[int, tuple[str, float]] = {}
    if thin and engine is not None:
        try:
            read = engine(data, thin)
        except Exception:  # noqa: BLE001 - an OCR failure must not lose the text layer
            warnings.append("OCR failed on this file; pages without a text layer were not read.")
    chars = 0
    used: dict[int, float] = {}
    for i, (txt, hidden) in enumerate(pages, start=1):
        o_text, o_conf = read.get(i, ("", 0.0))
        if i in thin and len(o_text.strip()) > len(txt.strip()):
            used[i] = o_conf
            chars += len(o_text.strip())
            for para in _pdf_paragraphs(o_text):
                blocks.append(Block(text=para, page=i, heading=_looks_like_heading(para), ocr_confidence=o_conf))
            continue
        chars += len(txt.strip())
        for para in _pdf_paragraphs(txt):
            blocks.append(Block(text=para, page=i, heading=_looks_like_heading(para), hidden=_hidden_reason(para, hidden)))
    if used:
        detail = ", ".join(f"page {p} {c:.0f}/100" + (" (low)" if c < OCR_LOW_CONFIDENCE else "") for p, c in used.items())
        warnings.append(f"OCR: {len(used)} page(s) without a text layer were read by OCR (mean word confidence: {detail}). "
                        "OCR can misread words and numbers; check quotes against the original.")
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


def parse(kind: str, data: bytes, ocr: OcrFunc | None = None) -> RawDoc:
    if kind == "pdf":
        return parse_pdf(data, ocr)
    if kind == "docx":
        return parse_docx(data)
    return parse_text(data, markdown=(kind == "md"))
