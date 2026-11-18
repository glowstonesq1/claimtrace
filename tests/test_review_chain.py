"""Review trail hash chain (roadmap v1.0, signed review trail): tamper evidence for review decisions."""

from __future__ import annotations

import sqlite3
from importlib import resources

import pytest

from claimtrace.cli.main import main as cli
from claimtrace.core.models import ReviewDecision, ReviewDecisionKind, ReviewStatus
from claimtrace.core.store import GENESIS_HASH, Store


def _rev(i: int, target: str = "ans_1", note: str | None = None) -> ReviewDecision:
    return ReviewDecision(id=f"rev_{i}", target_kind="answer", target_id=target, decision=ReviewDecisionKind.accept,
                          note=note, reviewer="Sam", prior_status=ReviewStatus.unreviewed, target_hash="x")


def _three(store: Store) -> None:
    for i in (1, 2, 3):
        store.add_review(_rev(i, note=f"note {i}"))


def _force(store: Store, sql: str, args: tuple = ()) -> None:
    """An attacker with write access to the database file ignores the append-only triggers."""
    store.conn.execute("DROP TRIGGER IF EXISTS reviews_no_update")
    store.conn.execute("DROP TRIGGER IF EXISTS reviews_no_delete")
    store.conn.execute(sql, args)


def test_decisions_are_chained(store):
    _three(store)
    r1, r2, r3 = store.reviews()
    assert r1.prev_hash == GENESIS_HASH and r2.prev_hash == r1.hash and r3.prev_hash == r2.hash
    assert len({r1.hash, r2.hash, r3.hash}) == 3 and all(len(h or "") == 64 for h in (r1.hash, r2.hash, r3.hash))
    res = store.verify_review_chain()
    assert res["ok"] and res["checked"] == 3 and res["first_broken_id"] is None and res["head"] == r3.hash


def test_edited_decision_is_detected(store):
    _three(store)
    row = store.conn.execute("SELECT json FROM reviews WHERE id='rev_2'").fetchone()[0]
    _force(store, "UPDATE reviews SET json=? WHERE id='rev_2'", (row.replace("note 2", "note two"),))
    res = store.verify_review_chain()
    assert not res["ok"] and res["first_broken_id"] == "rev_2"


def test_rewritten_hash_is_detected_at_the_next_link(store):
    _three(store)
    row = store.conn.execute("SELECT json FROM reviews WHERE id='rev_2'").fetchone()[0]
    forged = row.replace("note 2", "note two")
    from claimtrace.core.store import chain_hash

    prev = store.conn.execute("SELECT prev_hash FROM reviews WHERE id='rev_2'").fetchone()[0]
    _force(store, "UPDATE reviews SET json=?, hash=? WHERE id='rev_2'", (forged, chain_hash(forged, prev)))
    res = store.verify_review_chain()
    assert not res["ok"] and res["first_broken_id"] == "rev_3"


def test_deleted_decision_is_detected(store):
    _three(store)
    _force(store, "DELETE FROM reviews WHERE id='rev_2'")
    res = store.verify_review_chain()
    assert not res["ok"] and res["first_broken_id"] == "rev_3"


def test_triggers_still_block_casual_edits(store):
    _three(store)
    with pytest.raises(sqlite3.DatabaseError):
        store.conn.execute("UPDATE reviews SET json='{}' WHERE id='rev_1'")
    with pytest.raises(sqlite3.DatabaseError):
        store.conn.execute("UPDATE reviews SET hash='0' WHERE id='rev_1'")
    with pytest.raises(sqlite3.DatabaseError):
        store.conn.execute("DELETE FROM reviews WHERE id='rev_1'")


def test_document_deletion_redacts_without_breaking_the_chain(loaded, store):
    from claimtrace.core.models import Commitment

    doc = loaded["msa-v1.md"]
    c = store.objects(Commitment, doc)[0]
    store.add_review(_rev(1, target="ans_other"))
    store.add_review(_rev(2, target=c.id, note="secret canary note"))
    store.add_review(_rev(3, target="ans_other"))
    counts = store.delete_document(doc)
    assert counts["reviews"] == 1
    assert [r.id for r in store.reviews()] == ["rev_1", "rev_3"]
    assert "secret canary" not in str(store.conn.execute("SELECT json FROM reviews").fetchall())
    res = store.verify_review_chain()
    assert res["ok"] and res["redacted"] == 1 and res["checked"] == 3


def test_v01_database_is_backfilled_on_upgrade(tmp_path):
    db = str(tmp_path / "old.db")
    conn = sqlite3.connect(db, isolation_level=None)
    sql = resources.files("claimtrace.core").joinpath("migrations").joinpath("001_init.sql").read_text()
    conn.executescript(f"BEGIN;\nCREATE TABLE schema_version (version INTEGER NOT NULL);\n{sql}\n"
                       "INSERT INTO schema_version VALUES (1);\nCOMMIT;")
    for i in (1, 2):
        r = _rev(i)
        conn.execute("INSERT INTO reviews(id, target_kind, target_id, json, at) VALUES (?,?,?,?,?)",
                     (r.id, r.target_kind, r.target_id, r.model_dump_json(exclude={"prev_hash", "hash"}), r.at.isoformat()))
    conn.close()
    store = Store(db)
    res = store.verify_review_chain()
    assert res["ok"] and res["checked"] == 2
    store.add_review(_rev(3))
    assert store.verify_review_chain()["ok"]


def test_api_verify_chain(client, store):
    _three(store)
    r = client.get("/reviews/verify-chain")
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["checked"] == 3
    _force(store, "DELETE FROM reviews WHERE id='rev_1'")
    body = client.get("/reviews/verify-chain").json()
    assert body["ok"] is False and body["first_broken_id"] == "rev_2"


def test_cli_reviews_verify(tmp_path, capsys):
    db = str(tmp_path / "ct.db")
    store = Store(db)
    _three(store)
    assert cli(["--db", db, "reviews", "verify"]) == 0
    assert "OK" in capsys.readouterr().out
    _force(store, "DELETE FROM reviews WHERE id='rev_1'")
    store.conn.close()
    assert cli(["--db", db, "reviews", "verify"]) == 1
    assert "rev_2" in capsys.readouterr().out
