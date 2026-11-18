"""ClaimTrace REST API (FastAPI). OpenAPI docs at /docs.

Security defaults (design-review D13): loopback bind, same-origin check on unsafe methods, optional
bearer token (required when not bound to loopback), Host allowlist, token-bucket rate limit, structured
errors that never echo request bodies or document text.
"""


import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from claimtrace import __version__
from claimtrace.core.config import Settings
from claimtrace.core.models import (
    Answer,
    Claim,
    Commitment,
    Definition,
    DocType,
    Document,
    Lifecycle,
    Party,
    ReviewDecision,
    ReviewDecisionKind,
    VerificationRun,
    derive_status,
)
from claimtrace.core.store import NotFound, Store
from claimtrace.extraction import apply_amendments
from claimtrace.extraction.analyze import execute_run, start_run
from claimtrace.ingestion import IngestError, IngestOptions, ingest_bytes
from claimtrace.ingestion.pipeline import MAX_UPLOAD_BYTES
from claimtrace.integrations.llm import LLMProvider, provider_from_settings
from claimtrace.verification import answer_question, verify_documents
from claimtrace.verification.report import build_report, deadlines_csv, deadlines_ics, render_html, render_markdown

log = logging.getLogger("claimtrace")
STATIC_DIR = Path(__file__).parent / "static"
SAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples" / "documents"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


# ------------------------------------------------------------------ logging (ids and counts only)
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": datetime.now(UTC).isoformat(), "level": record.levelname, "event": record.getMessage()}
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter())
    log.handlers = [h]
    log.setLevel(logging.INFO)
    log.propagate = False


def event(name: str, **fields: object) -> None:
    """Log an event. Callers pass IDs, counts and durations only, never text, questions or filenames."""
    log.info(name, extra={"fields": fields})


# ------------------------------------------------------------------ errors
class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None) -> None:
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def _err(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message,
                                                               "details": details or {}}})


# ------------------------------------------------------------------ request/response bodies
class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    document_ids: list[str] | None = Field(default=None, max_length=50)


class VerifyRequest(BaseModel):
    base_document_id: str
    other_document_id: str


class ReviewRequest(BaseModel):
    decision: ReviewDecisionKind
    reviewer: str = Field(min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=4000)
    lifecycle: Lifecycle | None = None  # commitments only: human-set real-world state (D2)


class DocumentPatch(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    version_label: str | None = Field(default=None, max_length=50)
    doc_type: DocType | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    amends_document_id: str | None = None
    allow_external_llm: bool | None = None


class UrlIngest(BaseModel):
    url: str = Field(max_length=2000)
    title: str | None = None
    doc_type: DocType | None = None


# ------------------------------------------------------------------ middleware
class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.s = settings
        self.buckets: dict[str, tuple[float, float]] = {}
        self.lock = threading.Lock()

    def _rate_ok(self, key: str) -> bool:
        rate = self.s.rate_limit_per_minute / 60.0
        cap = float(self.s.rate_limit_per_minute)
        now = time.monotonic()
        with self.lock:
            tokens, last = self.buckets.get(key, (cap, now))
            tokens = min(cap, tokens + (now - last) * rate)
            if tokens < 1:
                self.buckets[key] = (tokens, now)
                return False
            self.buckets[key] = (tokens - 1, now)
            return True

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        allowed_hosts = LOOPBACK | {h for h in self.s.allowed_hosts}
        local_only = self.s.host in LOOPBACK or self.s.container_mode
        if local_only and not self.s.api_token and host and host not in allowed_hosts and host != "testserver":
            return _err(400, "bad_host", "Unexpected Host header (possible DNS rebinding).")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") not in self._origins(request):
                return _err(403, "bad_origin", "Cross-site requests are not allowed.")
        if self.s.api_token and request.url.path not in ("/health",) and not request.url.path.startswith(
                ("/assets", "/favicon")) and request.url.path != "/":
            auth = request.headers.get("authorization", "")
            given = auth[7:] if auth.lower().startswith("bearer ") else request.cookies.get("ct_token", "")
            if not hmac.compare_digest(given.encode(), self.s.api_token.encode()):
                return _err(401, "unauthorized", "A valid API token is required.")
        client = request.client.host if request.client else "unknown"
        if not self._rate_ok(client):
            return _err(429, "rate_limited", "Too many requests; slow down.")
        started = time.monotonic()
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        if not request.url.path.startswith(("/docs", "/redoc", "/openapi")):
            resp.headers.setdefault("Content-Security-Policy",
                                    "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                                    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        event("http", method=request.method, route=request.scope.get("route").path if request.scope.get("route") else
              "unmatched", status=resp.status_code, ms=round((time.monotonic() - started) * 1000))
        return resp

    def _origins(self, request: Request) -> set[str]:
        base = f"{request.url.scheme}://{request.headers.get('host', '')}"
        return {base.rstrip("/"), *self.s.allowed_origins}


# ------------------------------------------------------------------ app factory
def create_app(settings: Settings | None = None, store: Store | None = None,
               provider: LLMProvider | None | Literal["auto"] = "auto") -> FastAPI:
    settings = settings or Settings()
    if settings.host not in LOOPBACK and not settings.api_token and not settings.container_mode:
        raise RuntimeError("Refusing to start: binding to a non-loopback address requires CLAIMTRACE_API_TOKEN.")
    if store is None:
        Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
        store = Store(settings.db_path)
    llm = provider_from_settings(settings) if provider == "auto" else provider
    configure_logging()
    app = FastAPI(
        title="ClaimTrace API", version=__version__,
        description="Upload documents, map commitments, ask grounded questions and verify against exact source "
                    "text. **Not legal advice.**",
    )
    app.state.store, app.state.settings, app.state.llm = store, settings, llm
    app.add_middleware(SecurityMiddleware, settings=settings)

    # -------------------------------------------------------------- error handlers
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError) -> JSONResponse:
        return _err(e.status, e.code, e.message, e.details)

    @app.exception_handler(NotFound)
    async def _nf(_: Request, e: NotFound) -> JSONResponse:
        return _err(404, "not_found", f"Not found: {str(e).split(' ')[0]}.")

    @app.exception_handler(IngestError)
    async def _ingest(_: Request, e: IngestError) -> JSONResponse:
        status = 413 if e.code == "file_too_large" else 415 if e.code in ("unsupported_file_type", "type_mismatch") \
            else 422
        return _err(status, e.code, e.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError) -> JSONResponse:
        # never echo the submitted values (they may contain document text)
        fields = [{"field": ".".join(str(p) for p in err.get("loc", [])), "problem": err.get("type")}
                  for err in e.errors()]
        return _err(422, "invalid_request", "The request is not valid.", {"fields": fields})

    @app.exception_handler(HTTPException)
    async def _http(_: Request, e: HTTPException) -> JSONResponse:
        return _err(e.status_code, "http_error", str(e.detail) if e.status_code < 500 else "Server error.")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, e: Exception) -> JSONResponse:
        event("unhandled_error", error_type=type(e).__name__)
        return _err(500, "internal_error", "Something went wrong. No document content was logged.")

    def st() -> Store:
        return app.state.store  # type: ignore[no-any-return]

    S = Annotated[Store, Depends(st)]

    # -------------------------------------------------------------- health
    @app.get("/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok", "version": __version__, "config": settings.public()}

    # -------------------------------------------------------------- documents
    @app.post("/documents", response_model=Document, status_code=201, tags=["documents"])
    async def upload(
        store: S,
        file: Annotated[UploadFile | None, File()] = None,
        url: Annotated[str | None, Form()] = None,
        title: Annotated[str | None, Form(max_length=300)] = None,
        version_label: Annotated[str | None, Form(max_length=50)] = None,
        doc_type: Annotated[DocType | None, Form()] = None,
        amends_document_id: Annotated[str | None, Form()] = None,
        allow_external_llm: Annotated[bool, Form()] = False,
    ) -> Document:
        opts = IngestOptions(title=title, version_label=version_label, doc_type=doc_type.value if doc_type else None,
                             amends_document_id=amends_document_id, allow_external_llm=allow_external_llm)
        if amends_document_id:
            store.get_document(amends_document_id)
        if url:
            if not settings.allow_url_ingestion:
                raise ApiError(403, "url_ingestion_disabled", "URL ingestion is turned off. Set "
                                                              "CLAIMTRACE_ALLOW_URL_INGESTION=true to enable it.")
            from claimtrace.ingestion.url import fetch_url
            name, data = fetch_url(url)
            opts.source = "url"
        elif file is not None:
            data = await _read_capped(file)
            name = file.filename or "upload"
        else:
            raise ApiError(422, "missing_file", "Send a file or a URL.")
        doc = ingest_bytes(store, name, data, opts)
        apply_amendments(store)
        event("document_ingested", document_id=doc.id, passages=len(store.passages(doc.id)), bytes=len(data))
        return doc

    @app.get("/documents", response_model=list[Document], tags=["documents"])
    def list_documents(store: S) -> list[Document]:
        return store.list_documents()

    @app.get("/documents/{doc_id}", tags=["documents"])
    def get_document(doc_id: str, store: S) -> dict:
        doc = store.get_document(doc_id)
        return {"document": doc.model_dump(mode="json"),
                "passages": [p.model_dump(mode="json") for p in store.passages(doc_id)],
                "parties": [p.model_dump(mode="json") for p in store.objects(Party, doc_id)],
                "definitions": [d.model_dump(mode="json") for d in store.objects(Definition, doc_id)],
                "amended_by": [d.id for d in store.list_documents() if d.amends_document_id == doc_id]}

    @app.patch("/documents/{doc_id}", response_model=Document, tags=["documents"])
    def patch_document(doc_id: str, body: DocumentPatch, store: S) -> Document:
        doc = store.get_document(doc_id)
        data = body.model_dump(exclude_unset=True)
        if data.get("amends_document_id"):
            if data["amends_document_id"] == doc_id:
                raise ApiError(422, "invalid_relation", "A document cannot amend itself.")
            store.get_document(data["amends_document_id"])
        doc = doc.model_copy(update=data)
        store.update_document(doc)
        apply_amendments(store)
        return doc

    @app.delete("/documents/{doc_id}", tags=["documents"])
    def delete_document(doc_id: str, store: S) -> dict:
        counts = store.delete_document(doc_id)
        apply_amendments(store)
        event("document_deleted", document_id=doc_id, **counts)
        return {"deleted": doc_id, "removed": counts,
                "note": "All text and derived data were removed. A content-free record (ID, checksum, time) is kept."}

    @app.post("/documents/{doc_id}/analyze", status_code=202, tags=["analysis"])
    def analyze(doc_id: str, store: S, background: BackgroundTasks) -> dict:
        store.get_document(doc_id)
        run, created = start_run(store, doc_id, app.state.llm)
        if created or run.status == "failed":
            background.add_task(_run_analysis, store, run, app.state.llm)
        return {"run": run.model_dump(mode="json"), "poll": f"/runs/{run.id}"}

    @app.get("/runs/{run_id}", tags=["analysis"])
    def get_run(run_id: str, store: S) -> dict:
        return store.get_run(run_id).model_dump(mode="json")

    @app.get("/documents/{doc_id}/commitments", response_model=list[Commitment], tags=["analysis"])
    def commitments(doc_id: str, store: S, type: str | None = None, party: str | None = None,
                    status: str | None = None, due_before: str | None = None,
                    needs_review: bool | None = None, include_amendments: bool = True) -> list[Commitment]:
        store.get_document(doc_id)
        items = store.objects(Commitment, doc_id)
        if include_amendments:
            for d in store.list_documents():
                if d.amends_document_id == doc_id:
                    items += store.objects(Commitment, d.id)
        out = []
        for c in items:
            c.provenance.review_status = store.current_review_status(c.id)
            if type and c.type.value != type:
                continue
            if party and (c.obliging_party or "").lower() != party.lower():
                continue
            if status and c.status.value != status and c.document_effect.value != status:
                continue
            if needs_review is not None and c.needs_review != needs_review:
                continue
            if due_before and not (c.deadline and c.deadline.date and c.deadline.date.isoformat() <= due_before):
                continue
            out.append(c)
        return out

    @app.get("/documents/{doc_id}/claims", response_model=list[Claim], tags=["analysis"])
    def claims(doc_id: str, store: S) -> list[Claim]:
        store.get_document(doc_id)
        return store.objects(Claim, doc_id)

    @app.get("/documents/{doc_id}/graph", tags=["analysis"])
    def graph(doc_id: str, store: S) -> dict:
        doc = store.get_document(doc_id)
        nodes = [{"id": doc.id, "type": "document", "label": f"{doc.title} ({doc.version_label})"}]
        for p in store.objects(Party, doc_id):
            nodes.append({"id": p.id, "type": "party", "label": p.alias or p.name, "name": p.name})
        for c in store.objects(Commitment, doc_id):
            nodes.append({"id": c.id, "type": "commitment", "label": f"§{c.section_number or '?'} {c.type.value}",
                          "text": c.text, "status": c.status.value, "provenance": c.provenance.model_dump(mode="json")})
        for c in store.objects(Claim, doc_id):
            nodes.append({"id": c.id, "type": "claim", "label": f"§{c.section_number or '?'} {c.claim_type}",
                          "text": c.text, "provenance": c.provenance.model_dump(mode="json")})
        edges = store.edges(doc_id)
        known = {n["id"] for n in nodes}
        for e in edges:
            for end in (e.src_id, e.dst_id):
                if end not in known:
                    kind = end.split(":", 1)[0] if ":" in end else "external"
                    nodes.append({"id": end, "type": kind, "label": end.split(":", 1)[-1][:80]})
                    known.add(end)
        return {"nodes": nodes, "edges": [e.model_dump(mode="json") for e in edges]}

    # -------------------------------------------------------------- ask / verify
    @app.post("/ask", response_model=Answer, tags=["questions"])
    def ask(body: AskRequest, store: S) -> Answer:
        started = time.monotonic()
        ans = answer_question(store, body.question, body.document_ids, provider=app.state.llm)
        event("ask", answer_id=ans.id, status=ans.status.value, citations=len(ans.citations),
              ms=round((time.monotonic() - started) * 1000))
        return ans

    @app.get("/answers/{answer_id}", response_model=Answer, tags=["questions"])
    def get_answer(answer_id: str, store: S) -> Answer:
        a = store.get_answer(answer_id)
        a.review_status = store.current_review_status(a.id)
        return a

    @app.post("/verify", response_model=VerificationRun, tags=["verification"])
    def verify(body: VerifyRequest, store: S) -> VerificationRun:
        if body.base_document_id == body.other_document_id:
            raise ApiError(422, "same_document", "Choose two different documents.")
        run = verify_documents(store, body.base_document_id, body.other_document_id)
        event("verify", run_id=run.id, mode=run.mode, findings=len(run.findings))
        return run

    @app.get("/verifications/{run_id}", response_model=VerificationRun, tags=["verification"])
    def get_verification(run_id: str, store: S) -> VerificationRun:
        run = store.get_verification(run_id)
        for f in run.findings:
            f.review_status = store.current_review_status(f.id)
        return run

    @app.get("/documents/{doc_id}/verifications", response_model=list[VerificationRun], tags=["verification"])
    def doc_verifications(doc_id: str, store: S) -> list[VerificationRun]:
        runs = store.verifications_for_document(doc_id)
        for r in runs:
            for f in r.findings:
                f.review_status = store.current_review_status(f.id)
        return runs

    # -------------------------------------------------------------- review (append-only)
    def _review(store: Store, kind: str, target_id: str, body: ReviewRequest) -> ReviewDecision:
        if kind == "answer":
            target = store.get_answer(target_id)
        elif kind == "finding":
            target = store.get_finding(target_id)  # type: ignore[assignment]
        else:
            target = store.get_object(Commitment, target_id)  # type: ignore[assignment]
        prior = store.current_review_status(target_id)
        r = ReviewDecision(id="rev_" + uuid.uuid4().hex[:12], target_kind=kind, target_id=target_id,
                           decision=body.decision, note=body.note, reviewer=body.reviewer.strip(),
                           reviewer_verified=False, prior_status=prior,
                           target_hash=hashlib.sha256(target.model_dump_json().encode()).hexdigest())
        store.add_review(r)
        if kind == "commitment" and body.lifecycle is not None:
            c: Commitment = target  # type: ignore[assignment]
            c.lifecycle = body.lifecycle
            c.status = derive_status(c)
            store.update_object(c)
        event("review", target_kind=kind, target_id=target_id, decision=body.decision.value)
        return r

    @app.post("/answers/{answer_id}/review", response_model=ReviewDecision, tags=["review"])
    def review_answer(answer_id: str, body: ReviewRequest, store: S) -> ReviewDecision:
        return _review(store, "answer", answer_id, body)

    @app.post("/findings/{finding_id}/review", response_model=ReviewDecision, tags=["review"])
    def review_finding(finding_id: str, body: ReviewRequest, store: S) -> ReviewDecision:
        return _review(store, "finding", finding_id, body)

    @app.post("/commitments/{commitment_id}/review", response_model=ReviewDecision, tags=["review"])
    def review_commitment(commitment_id: str, body: ReviewRequest, store: S) -> ReviewDecision:
        return _review(store, "commitment", commitment_id, body)

    @app.get("/reviews/verify-chain", tags=["review"])
    def verify_review_chain(store: S) -> dict:
        """Recompute the review hash chain; `first_broken_id` names the first decision that does not verify."""
        return store.verify_review_chain()

    @app.get("/reviews/{target_id}", response_model=list[ReviewDecision], tags=["review"])
    def get_reviews(target_id: str, store: S) -> list[ReviewDecision]:
        return store.reviews(target_id)

    # -------------------------------------------------------------- reports
    @app.get("/documents/{doc_id}/report", tags=["reports"], response_model=None)
    def report(doc_id: str, store: S, format: Literal["json", "md", "html"] = "json") -> Response:
        r = build_report(store, doc_id)
        if format == "md":
            return PlainTextResponse(render_markdown(r), media_type="text/markdown; charset=utf-8",
                                     headers={"Content-Disposition": f'attachment; filename="claimtrace-{doc_id}.md"'})
        if format == "html":
            return HTMLResponse(render_html(r), headers={"Content-Security-Policy": "default-src 'none'; "
                                                                                     "style-src 'unsafe-inline'"})
        return JSONResponse(r)

    @app.get("/documents/{doc_id}/deadlines.csv", tags=["reports"])
    def csv_export(doc_id: str, store: S) -> Response:
        store.get_document(doc_id)
        return PlainTextResponse(deadlines_csv(store, doc_id), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="deadlines-{doc_id}.csv"'})

    @app.get("/documents/{doc_id}/deadlines.ics", tags=["reports"])
    def ics_export(doc_id: str, store: S) -> Response:
        """In-force deadlines with a resolved date as an iCalendar file (download only; nothing is sent)."""
        store.get_document(doc_id)
        return Response(deadlines_ics(store, doc_id), media_type="text/calendar; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="deadlines-{doc_id}.ics"'})

    # -------------------------------------------------------------- privacy / samples
    @app.get("/privacy/egress", tags=["system"])
    def egress(store: S) -> dict:
        return {"sends": store.egress(), "note": "Every request ClaimTrace made to a language-model endpoint."}

    @app.get("/privacy/tombstones", tags=["system"])
    def tombstones(store: S) -> list[dict]:
        return store.tombstones()

    @app.post("/samples", tags=["system"])
    def load_samples(store: S) -> dict:
        """Load the bundled fictional sample documents and analyse them (first-run experience)."""
        order = [("msa-v1.md", None), ("amendment-1.md", None), ("audit-report-2026.md", None),
                 ("delivery-record.md", None)]
        loaded = []
        for name, _ in order:
            path = SAMPLES_DIR / name
            if not path.exists():
                raise ApiError(404, "samples_missing", "Sample documents are not installed.")
            doc = ingest_bytes(store, name, path.read_bytes(), IngestOptions(tags=["sample"]))
            loaded.append(doc)
        apply_amendments(store)
        for doc in loaded:
            run, created = start_run(store, doc.id, None)
            if created or run.status == "failed":
                execute_run(store, run, None)
        return {"loaded": [d.id for d in loaded]}

    # -------------------------------------------------------------- web UI
    if STATIC_DIR.exists() and (STATIC_DIR / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    # -------------------------------------------------------------- retention
    if settings.retention_days:
        _start_retention(store, settings.retention_days)
    return app


async def _read_capped(file: UploadFile) -> bytes:
    """Read an upload in chunks, refusing as soon as the cap is exceeded (not after reading it all)."""
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf.extend(chunk)
        if len(buf) > MAX_UPLOAD_BYTES:
            raise IngestError("file_too_large", f"Files must be under {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    return bytes(buf)


def _run_analysis(store: Store, run, provider) -> None:  # type: ignore[no-untyped-def]
    started = time.monotonic()
    done = execute_run(store, run, provider)
    event("analysis_finished", run_id=done.id, document_id=done.document_id, status=done.status,
          ms=round((time.monotonic() - started) * 1000), **{k: v for k, v in done.counts.items() if isinstance(v, int)})


def purge_expired(store: Store, days: int) -> list[str]:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    removed = []
    for d in store.list_documents():
        if d.uploaded_at < cutoff:
            store.delete_document(d.id, reason=f"retention_{days}d")
            removed.append(d.id)
    if removed:
        apply_amendments(store)
    return removed


def _start_retention(store: Store, days: int) -> None:
    def loop() -> None:
        while True:
            removed = purge_expired(store, days)
            if removed:
                event("retention_purge", removed=len(removed))
            time.sleep(3600)

    threading.Thread(target=loop, daemon=True, name="retention").start()


def app_factory() -> FastAPI:
    return create_app()
