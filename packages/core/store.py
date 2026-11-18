"""SQLite persistence. The single persistence seam (design-review D11).

Objects are stored as validated JSON; reads re-validate, so a corrupted row fails loudly.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import resources
from typing import TypeVar

from pydantic import BaseModel

from .models import (
    DECISION_TO_STATUS,
    AmendmentInstruction,
    AnalysisRun,
    Answer,
    Claim,
    Commitment,
    Definition,
    Document,
    Edge,
    Finding,
    Party,
    Passage,
    ReviewDecision,
    ReviewDecisionKind,
    ReviewStatus,
    VerificationRun,
)

T = TypeVar("T", bound=BaseModel)
StoredObject = Commitment | Claim | Party | Definition | AmendmentInstruction

_KIND = {
    Commitment: "commitment",
    Claim: "claim",
    Party: "party",
    Definition: "definition",
    AmendmentInstruction: "amendment_instruction",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


class NotFound(Exception):
    pass


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.execute("PRAGMA foreign_keys=ON")
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    # ---- infrastructure -------------------------------------------------
    def _migrate(self) -> None:
        with self._lock:
            self.conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = self.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            current = row[0] or 0
            files = sorted(
                (f for f in resources.files("claimtrace.core").joinpath("migrations").iterdir() if f.name.endswith(".sql")),
                key=lambda f: f.name,
            )
            for f in files:
                version = int(f.name.split("_", 1)[0])
                if version > current:
                    # executescript manages its own transaction; keep schema + version atomic
                    self.conn.executescript(f"BEGIN;\n{f.read_text()}\nINSERT INTO schema_version VALUES ({version});\nCOMMIT;")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self.conn.execute("BEGIN")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def _rows(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, args).fetchall()

    # ---- documents ------------------------------------------------------
    def add_document(self, doc: Document, text: str, passages: list[Passage]) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO documents(id, checksum, title, text, json, created_at) VALUES (?,?,?,?,?,?)",
                (doc.id, doc.checksum_sha256, doc.title, text, doc.model_dump_json(), _now()),
            )
            c.executemany(
                "INSERT INTO passages(id, document_id, ordinal, json) VALUES (?,?,?,?)",
                [(p.id, p.document_id, p.ordinal, p.model_dump_json()) for p in passages],
            )

    def update_document(self, doc: Document) -> None:
        with self.tx() as c:
            c.execute("UPDATE documents SET json=?, title=? WHERE id=?", (doc.model_dump_json(), doc.title, doc.id))

    def get_document(self, doc_id: str) -> Document:
        rows = self._rows("SELECT json FROM documents WHERE id=?", (doc_id,))
        if not rows:
            raise NotFound(f"document {doc_id}")
        return Document.model_validate_json(rows[0][0])

    def get_document_text(self, doc_id: str) -> str:
        rows = self._rows("SELECT text FROM documents WHERE id=?", (doc_id,))
        if not rows:
            raise NotFound(f"document {doc_id}")
        return str(rows[0][0])

    def list_documents(self) -> list[Document]:
        return [Document.model_validate_json(r[0]) for r in self._rows("SELECT json FROM documents ORDER BY created_at")]

    def find_by_checksum(self, checksum: str) -> Document | None:
        rows = self._rows("SELECT json FROM documents WHERE checksum=?", (checksum,))
        return Document.model_validate_json(rows[0][0]) if rows else None

    def passages(self, doc_id: str) -> list[Passage]:
        rows = self._rows("SELECT json FROM passages WHERE document_id=? ORDER BY ordinal", (doc_id,))
        return [Passage.model_validate_json(r[0]) for r in rows]

    def get_passage(self, passage_id: str) -> Passage:
        rows = self._rows("SELECT json FROM passages WHERE id=?", (passage_id,))
        if not rows:
            raise NotFound(f"passage {passage_id}")
        return Passage.model_validate_json(rows[0][0])

    # ---- extracted objects ---------------------------------------------
    def replace_extraction(self, doc_id: str, objects: list[StoredObject], edges: list[Edge]) -> None:
        """Atomically swap a document's extracted objects and its edges."""
        with self.tx() as c:
            c.execute("DELETE FROM objects WHERE document_id=?", (doc_id,))
            c.execute("DELETE FROM edges WHERE document_id=?", (doc_id,))
            for o in objects:
                c.execute(
                    "INSERT INTO objects(id, kind, document_id, section_number, json) VALUES (?,?,?,?,?)",
                    (
                        o.id,
                        _KIND[type(o)],
                        o.document_id,
                        getattr(o, "section_number", None),  # type: ignore[attr-defined]
                        o.model_dump_json(),
                    ),
                )
            for e in edges:
                c.execute(
                    "INSERT INTO edges(id, src_id, dst_id, type, document_id, json) VALUES (?,?,?,?,?,?)",
                    (e.id, e.src_id, e.dst_id, e.type.value, e.document_id, e.model_dump_json()),
                )

    def objects(self, model: type[T], doc_id: str | None = None) -> list[T]:
        kind = _KIND[model]
        if doc_id:
            rows = self._rows("SELECT json FROM objects WHERE kind=? AND document_id=? ORDER BY rowid", (kind, doc_id))
        else:
            rows = self._rows("SELECT json FROM objects WHERE kind=? ORDER BY rowid", (kind,))
        return [model.model_validate_json(r[0]) for r in rows]

    def get_object(self, model: type[T], obj_id: str) -> T:
        rows = self._rows("SELECT json FROM objects WHERE id=? AND kind=?", (obj_id, _KIND[model]))
        if not rows:
            raise NotFound(f"{_KIND[model]} {obj_id}")
        return model.model_validate_json(rows[0][0])

    def add_objects(self, objs: list[StoredObject]) -> None:
        with self.tx() as c:
            for o in objs:
                c.execute(
                    "INSERT OR REPLACE INTO objects(id, kind, document_id, section_number, json) VALUES (?,?,?,?,?)",
                    (
                        o.id,
                        _KIND[type(o)],
                        o.document_id,
                        getattr(o, "section_number", None),  # type: ignore[attr-defined]
                        o.model_dump_json(),
                    ),
                )

    def delete_objects_with_prefix(self, prefix: str) -> None:
        with self.tx() as c:
            # substr, not LIKE: "_" is a LIKE wildcard and would match unrelated ids
            c.execute("DELETE FROM objects WHERE substr(id, 1, ?) = ?", (len(prefix), prefix))

    def update_object(self, obj: StoredObject) -> None:
        with self.tx() as c:
            c.execute("UPDATE objects SET json=? WHERE id=?", (obj.model_dump_json(), obj.id))  # type: ignore[attr-defined]

    def add_edges(self, edges: list[Edge]) -> None:
        with self.tx() as c:
            for e in edges:
                c.execute(
                    "INSERT OR REPLACE INTO edges(id, src_id, dst_id, type, document_id, json) VALUES (?,?,?,?,?,?)",
                    (e.id, e.src_id, e.dst_id, e.type.value, e.document_id, e.model_dump_json()),
                )

    def delete_edges_of_type(self, edge_type: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM edges WHERE type=? AND document_id IS NULL", (edge_type,))

    def edges(self, doc_id: str | None = None) -> list[Edge]:
        if doc_id:
            rows = self._rows(
                "SELECT json FROM edges WHERE document_id=? OR src_id IN (SELECT id FROM objects WHERE document_id=?)"
                " OR dst_id IN (SELECT id FROM objects WHERE document_id=?) OR src_id=? OR dst_id=?",
                (doc_id, doc_id, doc_id, doc_id, doc_id),
            )
        else:
            rows = self._rows("SELECT json FROM edges")
        return [Edge.model_validate_json(r[0]) for r in rows]

    # ---- runs -------------------------------------------------------------
    def find_run(self, idem_key: str) -> AnalysisRun | None:
        rows = self._rows("SELECT json FROM analysis_runs WHERE idem_key=? ORDER BY rowid DESC", (idem_key,))
        for r in rows:
            run = AnalysisRun.model_validate_json(r[0])
            if run.status != "failed":
                return run
        return None

    def save_run(self, run: AnalysisRun, idem_key: str) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO analysis_runs(id, document_id, idem_key, json) VALUES (?,?,?,?)",
                (run.id, run.document_id, idem_key, run.model_dump_json()),
            )

    def get_run(self, run_id: str) -> AnalysisRun:
        rows = self._rows("SELECT json FROM analysis_runs WHERE id=?", (run_id,))
        if not rows:
            raise NotFound(f"run {run_id}")
        return AnalysisRun.model_validate_json(rows[0][0])

    # ---- answers & verification ----------------------------------------
    def save_answer(self, a: Answer) -> None:
        cited = {c.span.document_id for c in a.citations} | set(a.document_ids)
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO answers(id, json, created_at) VALUES (?,?,?)", (a.id, a.model_dump_json(), _now()))
            for d in cited:
                c.execute("INSERT OR IGNORE INTO answer_documents VALUES (?,?)", (a.id, d))

    def get_answer(self, answer_id: str) -> Answer:
        rows = self._rows("SELECT json FROM answers WHERE id=?", (answer_id,))
        if not rows:
            raise NotFound(f"answer {answer_id}")
        return Answer.model_validate_json(rows[0][0])

    def answers_for_document(self, doc_id: str) -> list[Answer]:
        rows = self._rows(
            "SELECT a.json FROM answers a JOIN answer_documents d ON a.id=d.answer_id WHERE d.document_id=?"
            " ORDER BY a.created_at",
            (doc_id,),
        )
        return [Answer.model_validate_json(r[0]) for r in rows]

    def update_answer(self, a: Answer) -> None:
        with self.tx() as c:
            c.execute("UPDATE answers SET json=? WHERE id=?", (a.model_dump_json(), a.id))

    def save_verification(self, run: VerificationRun) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO verification_runs(id, base_document_id, other_document_id, json, created_at) VALUES (?,?,?,?,?)",
                (run.id, run.base_document_id, run.other_document_id, run.model_dump_json(), _now()),
            )
            for f in run.findings:
                c.execute("INSERT INTO findings(id, run_id, json) VALUES (?,?,?)", (f.id, run.id, f.model_dump_json()))

    def get_verification(self, run_id: str) -> VerificationRun:
        rows = self._rows("SELECT json FROM verification_runs WHERE id=?", (run_id,))
        if not rows:
            raise NotFound(f"verification {run_id}")
        run = VerificationRun.model_validate_json(rows[0][0])
        run.findings = [self.get_finding(f.id) for f in run.findings]
        return run

    def verifications_for_document(self, doc_id: str) -> list[VerificationRun]:
        rows = self._rows(
            "SELECT id FROM verification_runs WHERE base_document_id=? OR other_document_id=? ORDER BY created_at",
            (doc_id, doc_id),
        )
        return [self.get_verification(r[0]) for r in rows]

    def get_finding(self, finding_id: str) -> Finding:
        rows = self._rows("SELECT json FROM findings WHERE id=?", (finding_id,))
        if not rows:
            raise NotFound(f"finding {finding_id}")
        return Finding.model_validate_json(rows[0][0])

    def update_finding(self, f: Finding) -> None:
        with self.tx() as c:
            c.execute("UPDATE findings SET json=? WHERE id=?", (f.model_dump_json(), f.id))

    # ---- reviews (append-only) -------------------------------------------
    def add_review(self, r: ReviewDecision) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO reviews(id, target_kind, target_id, json, at) VALUES (?,?,?,?,?)",
                (r.id, r.target_kind, r.target_id, r.model_dump_json(), r.at.isoformat()),
            )

    def reviews(self, target_id: str | None = None) -> list[ReviewDecision]:
        if target_id:
            rows = self._rows("SELECT json FROM reviews WHERE target_id=? ORDER BY at, rowid", (target_id,))
        else:
            rows = self._rows("SELECT json FROM reviews ORDER BY at, rowid")
        return [ReviewDecision.model_validate_json(r[0]) for r in rows]

    def current_review_status(self, target_id: str) -> ReviewStatus:
        status = ReviewStatus.unreviewed
        for r in self.reviews(target_id):
            if r.decision != ReviewDecisionKind.note:
                status = DECISION_TO_STATUS[r.decision]
        return status

    # ---- egress ------------------------------------------------------------
    def log_egress(self, document_id: str | None, host: str, nbytes: int, purpose: str) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO egress_log(document_id, host, bytes, purpose, at) VALUES (?,?,?,?,?)",
                (document_id, host, nbytes, purpose, _now()),
            )

    def egress(self) -> list[dict]:
        rows = self._rows("SELECT document_id, host, bytes, purpose, at FROM egress_log ORDER BY id")
        return [dict(zip(("document_id", "host", "bytes", "purpose", "at"), r, strict=True)) for r in rows]

    # ---- deletion (design-review D15) -------------------------------------
    def delete_document(self, doc_id: str, reason: str = "user_request") -> dict[str, int]:
        doc = self.get_document(doc_id)
        with self.tx() as c:
            obj_ids = [r[0] for r in c.execute("SELECT id FROM objects WHERE document_id=?", (doc_id,))]
            ans_ids = [r[0] for r in c.execute("SELECT answer_id FROM answer_documents WHERE document_id=?", (doc_id,))]
            run_ids = [
                r[0]
                for r in c.execute(
                    "SELECT id FROM verification_runs WHERE base_document_id=? OR other_document_id=?", (doc_id, doc_id)
                )
            ]
            finding_ids = (
                [r[0] for r in c.execute(f"SELECT id FROM findings WHERE run_id IN ({','.join('?' * len(run_ids))})", run_ids)]
                if run_ids
                else []
            )
            targets = obj_ids + ans_ids + finding_ids
            n_reviews = 0
            for i in range(0, len(targets), 500):
                chunk = targets[i : i + 500]
                n_reviews += c.execute(f"DELETE FROM reviews WHERE target_id IN ({','.join('?' * len(chunk))})", chunk).rowcount
            if obj_ids:
                for i in range(0, len(obj_ids), 500):
                    chunk = obj_ids[i : i + 500]
                    ph = ",".join("?" * len(chunk))
                    c.execute(f"DELETE FROM edges WHERE src_id IN ({ph}) OR dst_id IN ({ph})", chunk + chunk)
            c.execute("DELETE FROM edges WHERE src_id=? OR dst_id=?", (doc_id, doc_id))
            for a in ans_ids:
                c.execute("DELETE FROM answers WHERE id=?", (a,))
            counts = {"objects": len(obj_ids), "answers": len(ans_ids), "verification_runs": len(run_ids), "reviews": n_reviews}
            c.execute("DELETE FROM documents WHERE id=?", (doc_id,))  # cascades passages, objects, runs, findings
            c.execute(
                "INSERT OR REPLACE INTO tombstones VALUES (?,?,?,?,?)",
                (doc_id, doc.checksum_sha256, _now(), reason, json.dumps(counts)),
            )
        self.compact()
        return counts

    def compact(self) -> None:
        """Make deleted content unrecoverable from the database file (free pages, WAL)."""
        with self._lock:
            if self.path != ":memory:":
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.execute("VACUUM")
            if self.path != ":memory:":
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def tombstones(self) -> list[dict]:
        rows = self._rows("SELECT document_id, checksum, deleted_at, reason, counts FROM tombstones")
        return [
            {"document_id": r[0], "checksum": r[1], "deleted_at": r[2], "reason": r[3], "counts": json.loads(r[4])} for r in rows
        ]
