"""Optional OCR for PDF pages without a text layer (install with `.venv/bin/pip install -e '.[ocr]'` from a clone).

The engine is Tesseract via `pytesseract`, with pages rendered by `pypdfium2`. Both the Python
packages and the `tesseract` binary must be present; otherwise `default_ocr()` returns None and
scanned PDFs are flagged exactly as in v0.1. Set `CLAIMTRACE_OCR=off` to disable OCR even when it
is installed.

The seam is a plain function `OcrFunc(pdf_bytes, page_numbers) -> {page: (text, confidence)}` with
1-based page numbers and a mean word confidence from 0 to 100, so tests (and other engines) can
inject their own.
"""

from __future__ import annotations

import io
import os
import shutil
from collections.abc import Callable

OcrFunc = Callable[[bytes, list[int]], dict[int, tuple[str, float]]]

RENDER_DPI = 300


def default_ocr() -> OcrFunc | None:
    """The Tesseract engine if it is installed and not disabled, else None."""
    if os.environ.get("CLAIMTRACE_OCR", "auto").strip().lower() in ("off", "0", "false", "no"):
        return None
    if shutil.which("tesseract") is None:
        return None
    try:
        import pypdfium2  # noqa: F401
        import pytesseract  # noqa: F401
    except ImportError:
        return None
    return tesseract_ocr


def tesseract_ocr(data: bytes, pages: list[int]) -> dict[int, tuple[str, float]]:  # pragma: no cover - needs binary
    import pypdfium2 as pdfium
    import pytesseract

    pdf = pdfium.PdfDocument(io.BytesIO(data))
    out: dict[int, tuple[str, float]] = {}
    try:
        for n in pages:
            image = pdf[n - 1].render(scale=RENDER_DPI / 72).to_pil()
            d = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            lines: dict[tuple[int, int, int], list[str]] = {}
            confs: list[float] = []
            for i, word in enumerate(d["text"]):
                conf = float(d["conf"][i])
                if not word.strip() or conf < 0:
                    continue
                lines.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(word)
                confs.append(conf)
            paragraphs: dict[tuple[int, int], list[str]] = {}
            for (block, par, _line), words in sorted(lines.items()):
                paragraphs.setdefault((block, par), []).append(" ".join(words))
            text = "\n\n".join("\n".join(ls) for _, ls in sorted(paragraphs.items()))
            out[n] = (text, round(sum(confs) / len(confs), 1) if confs else 0.0)
    finally:
        pdf.close()
    return out
