"""Sandbox worker: reads {kind} + file bytes on stdin, writes RawDoc JSON on stdout.

Run only via sandbox.parse_sandboxed, which applies CPU/memory/time limits.
"""

import json
import sys

from claimtrace.ingestion.parsers import IngestError, parse


def main() -> None:
    kind = sys.stdin.buffer.readline().decode().strip()
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
