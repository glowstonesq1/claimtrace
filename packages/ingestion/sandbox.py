"""Run parsers in a separate process with CPU, memory and wall-clock limits (design-review D12).

PDFs are parsed in two sandboxed steps. The text layer is read first, under the limits below; a failure
there rejects the file as before. OCR of pages without a text layer then runs in its own process with a
per-page time budget: a page OCR cannot finish in time (or an engine crash) is skipped with a warning,
and the document is kept with its text layer and the SCANNED warning, as in v0.1. OCR running out of
time never rejects an upload.
"""

from __future__ import annotations

import functools
import json
import os
import select
import subprocess
import sys
import threading
import time
from pathlib import Path

from .ocr import OcrFunc, default_ocr
from .parsers import OCR_FAILED, Block, IngestError, RawDoc, finish_pdf

CPU_SECONDS = 30
MEMORY_BYTES = 1024 * 1024 * 1024
WALL_SECONDS = 60

# OCR: each page gets its own wall-clock budget (rendering at 300 dpi + Tesseract is a few seconds a
# page); the first page of each OCR process also gets the process start-up time. The whole step stops
# after OCR_TOTAL_SECONDS; pages not reached are reported, not fatal.
OCR_PAGE_SECONDS = 30.0
OCR_STARTUP_SECONDS = 15.0
OCR_TOTAL_SECONDS = 600.0


def _limits(cpu_seconds: int = CPU_SECONDS) -> None:  # pragma: no cover - runs in the child
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def _run_worker(kind: str, data: bytes) -> RawDoc:
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-m", "claimtrace.ingestion.worker"],
            input=kind.encode() + b"\n" + data,
            capture_output=True,
            timeout=WALL_SECONDS,
            preexec_fn=_limits if sys.platform != "win32" else None,  # noqa: PLW1509
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise IngestError("resource_limit", "Parsing took too long and was stopped.") from e
    if proc.returncode != 0 or not proc.stdout:
        raise IngestError("resource_limit", "Parsing was stopped (time or memory limit, or a parser crash).")
    out = json.loads(proc.stdout)
    if not out["ok"]:
        raise IngestError(out["code"], out["message"])
    d = out["doc"]
    d["blocks"] = [Block(**b) for b in d["blocks"]]
    return RawDoc(**d)


def parse_sandboxed(kind: str, data: bytes, ocr: OcrFunc | None = None) -> RawDoc:
    """Parse in a limited child process. `ocr` overrides the installed OCR engine (it must be importable
    by module path, as the OCR step runs in a separate process)."""
    if kind != "pdf":
        return _run_worker(kind, data)
    raw = _run_worker("pdf-text", data)
    pages = [page for page, _ in raw.ocr_pending]
    engine = ocr if ocr is not None else default_ocr()
    if not pages or engine is None:
        return finish_pdf(raw, {})
    read, timed_out, failed = ocr_sandboxed(engine, data, pages)
    notes: list[str] = []
    if failed and not read and not timed_out:
        notes.append(OCR_FAILED)
    elif failed:
        notes.append(f"OCR failed on page(s) {_pages(failed)}; they were not read.")
    if timed_out:
        notes.append(
            f"OCR: {len(timed_out)} page(s) could not be read within the time limit (page(s) {_pages(timed_out)}); "
            "they were kept without OCR text."
        )
    return finish_pdf(raw, read, notes)


def _pages(pages: list[int]) -> str:
    return ", ".join(str(p) for p in sorted(pages))


def _engine_spec(engine: OcrFunc) -> dict[str, str]:
    """How the OCR worker imports `engine`: module, attribute, and the sys.path root it was imported from
    (the worker runs with `python -I`, so only installed packages are importable by default)."""
    module, name = engine.__module__, engine.__qualname__
    if "<" in name or module == "__main__":
        raise ValueError("the OCR engine must be a module-level function")
    root = ""
    file = getattr(sys.modules.get(module), "__file__", None)
    if file and not module.startswith("claimtrace."):
        root = str(Path(file).resolve().parents[module.count(".")])
    return {"module": module, "name": name, "root": root}


def ocr_sandboxed(
    engine: OcrFunc, data: bytes, pages: list[int]
) -> tuple[dict[int, tuple[str, float]], list[int], list[int]]:
    """OCR `pages` in a limited child process with a per-page budget.

    Returns (read pages, pages skipped for time, pages the engine failed on). When a page overruns, the
    process is killed and a fresh one continues with the next page.
    """
    spec = _engine_spec(engine)
    read: dict[int, tuple[str, float]] = {}
    timed_out: list[int] = []
    failed: list[int] = []
    todo = list(pages)
    deadline = time.monotonic() + OCR_TOTAL_SECONDS
    while todo:
        if time.monotonic() >= deadline:
            timed_out += todo
            break
        header = json.dumps({**spec, "pages": todo}).encode()
        cpu = int(OCR_PAGE_SECONDS * len(todo) + OCR_STARTUP_SECONDS) + 1
        proc = subprocess.Popen(
            [sys.executable, "-I", "-m", "claimtrace.ingestion.worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            preexec_fn=functools.partial(_limits, cpu) if sys.platform != "win32" else None,  # noqa: PLW1509
        )
        try:
            feeder = threading.Thread(target=_feed, args=(proc, b"ocr\n" + header + b"\n" + data), daemon=True)
            feeder.start()
            lines = _lines(proc)
            first = True
            while todo:
                budget = OCR_PAGE_SECONDS + (OCR_STARTUP_SECONDS if first else 0.0)
                first = False
                line = lines.next(min(budget, deadline - time.monotonic()))
                if line is _TIMEOUT:
                    timed_out.append(todo.pop(0))  # this page overran: kill and go on with the next one
                    break
                if line is None:  # the child died on this page (CPU/memory limit or a crash)
                    failed.append(todo.pop(0))
                    break
                try:
                    msg = json.loads(line)
                    page = int(msg["page"])
                except (ValueError, KeyError, TypeError):
                    failed.append(todo.pop(0))
                    break
                if page in todo:
                    todo.remove(page)
                if msg.get("ok") and msg.get("text") is not None:
                    read[page] = (str(msg["text"]), float(msg.get("conf", 0.0)))
                elif not msg.get("ok"):
                    failed.append(page)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            if proc.stdout is not None:
                proc.stdout.close()
    return read, timed_out, failed


def _feed(proc: subprocess.Popen[bytes], payload: bytes) -> None:
    try:
        assert proc.stdin is not None
        proc.stdin.write(payload)
        proc.stdin.close()
    except (BrokenPipeError, OSError, ValueError):
        pass  # the child exited early; its output (or lack of it) tells the reader what happened


_TIMEOUT = object()


class _lines:  # noqa: N801 - tiny reader, used like a function
    """Line reader over the child's stdout with a timeout per line (select + os.read, no buffering)."""

    def __init__(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdout is not None
        self.fd = proc.stdout.fileno()
        self.buf = b""
        self.eof = False

    def next(self, timeout: float) -> object:
        end = time.monotonic() + max(0.0, timeout)
        while b"\n" not in self.buf:
            if self.eof:
                return None
            left = end - time.monotonic()
            if left <= 0 or not select.select([self.fd], [], [], left)[0]:
                return _TIMEOUT
            chunk = os.read(self.fd, 65536)
            if not chunk:
                self.eof = True
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode("utf-8", "replace")
