"""Document ingestion: type checks, sandboxed parsing, passage segmentation, safe URL fetch."""

from .parsers import IngestError
from .pipeline import IngestOptions, ingest_bytes, ingest_file, segment

__all__ = ["IngestError", "IngestOptions", "ingest_bytes", "ingest_file", "segment"]
