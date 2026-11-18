"""Analysis orchestration: extract → store atomically → apply amendments → record a run manifest."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from claimtrace import __version__
from claimtrace.core.models import AnalysisRun
from claimtrace.core.store import Store
from claimtrace.core.text import NORMALIZER_VERSION
from claimtrace.integrations.llm import LLMProvider

from .apply import apply_amendments
from .llm import PROMPT_VERSION, extract_llm
from .rules import EXTRACTOR_VERSION, extract_rules


def idem_key(store: Store, doc_id: str, provider: LLMProvider | None) -> str:
    doc = store.get_document(doc_id)
    model = f"{provider.name}:{provider.model}" if provider else "rules"
    return f"{doc_id}:{doc.text_sha256}:{EXTRACTOR_VERSION}:{model}"


def start_run(store: Store, doc_id: str, provider: LLMProvider | None) -> tuple[AnalysisRun, bool]:
    """Return (run, created). An existing queued/running/done run for the same inputs is reused."""
    key = idem_key(store, doc_id, provider)
    existing = store.find_run(key)
    if existing:
        return existing, False
    run = AnalysisRun(id="run_" + uuid.uuid4().hex[:12], document_id=doc_id, extractor_version=EXTRACTOR_VERSION,
                      status="queued")
    store.save_run(run, key)
    return run, True


def execute_run(store: Store, run: AnalysisRun, provider: LLMProvider | None) -> AnalysisRun:
    key = idem_key(store, run.document_id, provider)
    doc = store.get_document(run.document_id)
    run.status = "running"
    store.save_run(run, key)
    doc.status = "analyzing"
    store.update_document(doc)
    try:
        passages = store.passages(doc.id)
        res = extract_rules(doc, passages)
        stats: dict[str, int] = {}
        if provider is not None:
            extra, stats = extract_llm(store, doc, passages, provider, res)
            res.commitments.extend(extra)
        store.replace_extraction(doc.id, res.objects(), res.edges)
        amended = apply_amendments(store)
        run.counts = {"commitments": len(res.commitments), "claims": len(res.claims), "parties": len(res.parties),
                      "definitions": len(res.definitions), "amendment_instructions": len(res.instructions),
                      "needs_review": sum(1 for c in res.commitments if c.needs_review),
                      "amended_commitments_total": amended, **stats}
        run.run_manifest = {
            "claimtrace_version": __version__, "document_checksum": doc.checksum_sha256,
            "text_sha256": doc.text_sha256, "normalizer_version": NORMALIZER_VERSION,
            "extractor_version": EXTRACTOR_VERSION, "model": provider.model if provider else None,
            "provider": provider.name if provider else "rules",
            "endpoint_host": provider.host if provider else None,
            "prompt_version": PROMPT_VERSION if provider else None,
        }
        run.status = "done"
        doc = store.get_document(doc.id)
        doc.status = "analyzed"
    except Exception as e:  # noqa: BLE001 - record and surface a safe message
        run.status = "failed"
        run.error = type(e).__name__ + (": " + str(e) if type(e).__name__ == "EgressNotAllowed" else "")
        doc = store.get_document(doc.id)
        doc.status = "failed"
    run.finished_at = datetime.now(UTC)
    store.save_run(run, key)
    store.update_document(doc)
    return run


def analyze_document(store: Store, doc_id: str, provider: LLMProvider | None = None) -> AnalysisRun:
    """Synchronous convenience wrapper (CLI, tests, eval)."""
    run, created = start_run(store, doc_id, provider)
    if not created and run.status == "done":
        return run
    return execute_run(store, run, provider)
