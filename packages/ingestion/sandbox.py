"""Run parsers in a separate process with CPU, memory and wall-clock limits (design-review D12)."""

from __future__ import annotations

import json
import subprocess
import sys

from .parsers import Block, IngestError, RawDoc

CPU_SECONDS = 30
MEMORY_BYTES = 1024 * 1024 * 1024
WALL_SECONDS = 60


def _limits() -> None:  # pragma: no cover - runs in the child
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def parse_sandboxed(kind: str, data: bytes) -> RawDoc:
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
