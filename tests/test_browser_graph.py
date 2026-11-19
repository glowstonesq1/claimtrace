"""claimtrace.browser.graph: the evidence map's model, shared by the home page (built from the samples) and the
try page (built in the browser from whatever was added)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from claimtrace.browser import Session, answer_graph, call, check_graph
from claimtrace.browser.graphs import MAX_GRAPH_CLIPS, MAX_GRAPH_DOCUMENTS, graph, lane_order

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "documents"
SAMPLES = ("amendment-1.md", "audit-report-2026.md", "delivery-record.md", "msa-v1.md")


@pytest.fixture(scope="module")
def session() -> Session:
    s = Session()
    s.analyze([{"name": n, "bytes": (EXAMPLES / n).read_bytes()} for n in SAMPLES])
    return s


def _texts(session: Session) -> dict[str, str]:
    return {d["id"]: session.document(d["id"])["text"] for d in session.register()["documents"]}


def _clips(g: dict) -> dict[str, tuple[dict, dict]]:
    return {c["id"]: (lane, c) for lane in g["lanes"] for c in lane["clips"]}


def test_primary_is_the_contract_then_its_amendment(session: Session) -> None:
    g = session.graph()
    assert [lane["type"] for lane in g["lanes"]] == ["contract", "amendment", "audit_report", "evidence"]
    assert g["primary"] == g["lanes"][0]["document_id"]
    assert g["shown"] == {"documents": [4, 4], "clips": [29, 29]}
    docs = [{"id": "a", "type": "evidence"}, {"id": "b", "type": "other"}]
    assert [d["id"] for d in lane_order(docs)] == ["a", "b"]  # no contract: the first added leads


def test_every_clip_is_verbatim_and_every_link_joins_two_clips(session: Session) -> None:
    g = session.graph()
    texts = _texts(session)
    clips = _clips(g)
    for cid, (lane, c) in clips.items():
        assert c["text"] and c["text"] in texts[lane["document_id"]], cid
        assert cid.startswith(lane["key"] + "-")
        assert c["state"] in {"in_force", "replaced", "review", "evidence"}
    for lk in g["links"]:
        assert lk["from"] in clips and lk["to"] in clips and lk["kind"] in g["kinds"], lk
        assert clips[lk["from"]][0]["key"] != clips[lk["to"]][0]["key"], "a link always joins two documents"
    replaced = [c for _l, c in clips.values() if c["state"] == "replaced"]
    assert {c["section"] for c in replaced} >= {"2.1", "3.2"}
    assert "Vendor" in {p for _l, c in clips.values() for p in c["parties"]}


def test_samples_output_equals_the_home_page_data(session: Session) -> None:
    """The home page's samples.json is this function's output (projected, then the home page withholds two
    clauses' wording): the builder calls graph(), so the two cannot drift."""
    spec = importlib.util.spec_from_file_location("build_site_data", ROOT / "scripts" / "build_site_data.py")
    assert spec and spec.loader
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    published = json.loads((ROOT / "apps" / "site" / "data" / "samples.json").read_text(encoding="utf-8"))
    docs = {d["type"]: d["id"] for d in session.register()["documents"]}
    g = graph(session, lanes=[(docs[t], k, n) for t, k, n in builder.LANES])
    lanes, links = builder.home_graph(g)
    assert lanes == published["lanes"] and links == published["links"] and g["kinds"] == published["kinds"]
    # withholding is the builder's step, never the engine's
    assert not any(c.get("withheld") for lane in g["lanes"] for c in lane["clips"])
    assert {c["id"] for lane in lanes for c in lane["clips"] if c.get("withheld")} == set(builder.WITHHELD_CLIPS)
    assert "WITHHELD" not in (ROOT / "packages" / "browser" / "graphs.py").read_text(encoding="utf-8")


def _big() -> Session:
    s = Session()
    files = []
    for n in range(MAX_GRAPH_DOCUMENTS + 2):
        clauses = "\n\n".join(f"{k}.1 The Supplier shall deliver item {n}-{k} within {k + 2} days." for k in range(1, 25))
        body = f'# Supply Agreement {n}\n\nThis Agreement is between Arden Ltd (the "Supplier") and Brook plc (the "Buyer").\n\n'
        files.append({"name": f"supply-{n}.md", "bytes": (body + clauses).encode()})
    s.analyze(files)
    return s


def test_caps_keep_the_map_small_and_say_so() -> None:
    s = _big()
    g = s.graph()
    total = len(s.register()["documents"])
    assert g["shown"]["documents"] == [MAX_GRAPH_DOCUMENTS, total]
    assert len(g["lanes"]) == MAX_GRAPH_DOCUMENTS
    n = sum(len(lane["clips"]) for lane in g["lanes"])
    assert n == g["shown"]["clips"][0] == MAX_GRAPH_CLIPS < g["shown"]["clips"][1]
    ids = {c["id"] for lane in g["lanes"] for c in lane["clips"]}
    assert all(lk["from"] in ids and lk["to"] in ids for lk in g["links"])
    small = s.graph(max_documents=2, max_clips=5)
    assert small["shown"]["documents"] == [2, total] and small["shown"]["clips"][0] == 5
    linked = {lk["from"] for lk in small["links"]} | {lk["to"] for lk in small["links"]}
    assert linked <= {c["id"] for lane in small["lanes"] for c in lane["clips"]}


def test_answer_graph_links_the_answer_to_each_cited_clause(session: Session) -> None:
    a = session.ask("Did the vendor promise delivery by March 31?")
    g = answer_graph(session, a)
    assert g["lanes"][0]["clips"][0]["node"] == "answer" and g["lanes"][0]["clips"][0]["text"] == a["answer_text"]
    clips = _clips(g)
    texts = _texts(session)
    rel = {clips[lk["to"]][1]["section"]: lk["kind"] for lk in g["links"]}
    assert rel["2.1"] == "replaced"  # the contract's March 31 clause was replaced by the amendment
    for lk in g["links"]:
        assert lk["from"] == "answer" and lk["kind"] in g["kinds"]
        lane, c = clips[lk["to"]]
        assert c["text"] in texts[lane["document_id"]]
    none = answer_graph(session, session.ask("What colour is the sky?"))
    assert none["links"] == [] and none["lanes"][0]["clips"][0]["status"] == "not_addressed"


def test_check_graph_carries_each_finding(session: Session) -> None:
    docs = {d["type"]: d["id"] for d in session.register()["documents"]}
    run = session.verify(docs["contract"], docs["audit_report"])
    g = check_graph(session, run)
    assert [lane["key"] for lane in g["lanes"]] == ["base", "other"]
    kinds = {lk["kind"] for lk in g["links"]}
    assert {"contradicts", "supports", "notmentioned"} <= kinds
    clips = _clips(g)
    for lk in g["links"]:
        f = run["findings"][lk["finding"]]
        assert clips[lk["to"]][1]["text"] and lk["note"] == f["explanation"]
        assert lk["from"] in clips
    assert clips["other-absent"][1]["node"] == "absent"


def test_call_ops_return_graphs(session: Session) -> None:  # noqa: ARG001 - the module session is separate
    from claimtrace import browser

    browser.reset()
    browser.analyze([{"name": n, "bytes": (EXAMPLES / n).read_bytes()} for n in SAMPLES])
    out = json.loads(call(json.dumps({"op": "graph"})))
    assert out["ok"] and len(out["result"]["lanes"]) == 4
    ask = json.loads(call(json.dumps({"op": "ask", "question": "Is customer data kept in the UK?", "graph": True})))
    assert ask["ok"] and ask["result"]["graph"]["view"] == "answer"
    plain = json.loads(call(json.dumps({"op": "ask", "question": "Is customer data kept in the UK?"})))
    assert "graph" not in plain["result"]
    lanes = out["result"]["lanes"]
    ver = json.loads(call(json.dumps({"op": "verify", "base_id": lanes[0]["document_id"],
                                      "other_id": lanes[3]["document_id"], "graph": True})))
    assert ver["ok"] and ver["result"]["graph"]["view"] == "check"
    browser.reset()
