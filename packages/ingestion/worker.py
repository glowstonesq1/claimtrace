"""Sandbox worker: reads {kind} + file bytes on stdin, writes RawDoc JSON on stdout.

Run only via sandbox.parse_sandboxed, which applies CPU/memory/time limits.
"""

import importlib
import json
import sys

from claimtrace.ingestion.parsers import IngestError, parse


def ocr_main(header: dict, data: bytes) -> None:
    """OCR step (sandbox.ocr_sandboxed): one JSON line per page, written as soon as the page is read."""
    if header.get("root"):
        sys.path.insert(0, header["root"])
    engine = getattr(importlib.import_module(header["module"]), header["name"])
    for page in header["pages"]:
        try:
            got = engine(data, [page]).get(page)
            msg = {"page": page, "ok": True, "text": got[0] if got else None, "conf": float(got[1]) if got else 0.0}
        except Exception:  # noqa: BLE001 - a failed page; never echo engine internals
            msg = {"page": page, "ok": False}
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()


def main() -> None:
    kind = sys.stdin.buffer.readline().decode().strip()
    if kind == "ocr":
        header = json.loads(sys.stdin.buffer.readline())
        ocr_main(header, sys.stdin.buffer.read())
        return
    data = sys.stdin.buffer.read()
    try:
        out = {"ok": True, "doc": parse(kind, data).to_dict()}
    except IngestError as e:
        out = {"ok": False, "code": e.code, "message": e.message}
    except MemoryError:
        out = {"ok": False, "code": "resource_limit", "message": "Parsing exceeded the memory limit."}
    except Exception:  # noqa: BLE001 - never echo parser internals (may include document text)
        out = {"ok": False, "code": "parse_failed", "message": "The file could not be parsed."}
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
