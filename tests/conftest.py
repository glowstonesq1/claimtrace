import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claimtrace.api.main import create_app
from claimtrace.core.config import Settings
from claimtrace.core.store import Store
from claimtrace.extraction import analyze_document
from claimtrace.ingestion import IngestOptions, ingest_file

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "documents"


@pytest.fixture
def store() -> Store:
    return Store()


@pytest.fixture
def loaded(store: Store) -> dict[str, str]:
    """All four sample documents ingested and analysed; returns name → document id."""
    ids = {}
    for name in ("msa-v1.md", "amendment-1.md", "audit-report-2026.md", "delivery-record.md"):
        doc = ingest_file(store, str(EXAMPLES / name), IngestOptions(sandbox=False))
        ids[name] = doc.id
    for doc_id in ids.values():
        analyze_document(store, doc_id)
    return ids


@pytest.fixture
def client(store: Store) -> TestClient:
    app = create_app(Settings(), store=store, provider=None)
    logging.getLogger("claimtrace").setLevel(logging.WARNING)
    return TestClient(app)


def make_client(store: Store, **settings) -> TestClient:
    s = Settings()
    for k, v in settings.items():
        setattr(s, k, v)
    return TestClient(create_app(s, store=store, provider=None))
