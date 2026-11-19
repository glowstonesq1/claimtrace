"""The evidence map's model: lanes (one per document), clips (one per cited section, its verbatim passage text)
and links between clips, built from engine output.

One source for both pictures of it: the home page's map (scripts/build_site_data.py runs ``graph`` on the
sample documents at build time) and the try page (the web worker runs it on whatever the person added).
apps/web/src/flow (React Flow, built to apps/site/vendor/flow) draws the result.

- ``graph(session)``: every document as a lane, its commitments as clips, the register's replacement links and
  the links found by checking the primary document (the contract, else the first added) against each other.
- ``answer_graph(session, answer)``: an ``ask`` result as a small graph, an answer node joined to the clauses
  it cites, each link named by its relation (states, replaced, not found, ...).
- ``check_graph(session, run)``: a ``verify`` result as two lanes, each finding a link carrying its index.

Clip text is always a slice of the stored document text (never rewritten), so it is verbatim by construction.
Big workspaces are capped (documents, clips); ``shown`` reports what was kept out of how many.
"""

from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from claimtrace.browser import Session

# The map stays readable, and the browser stays quick, up to about this size; past it the rest is listed as
# "showing N of M". Each document after the primary one costs one check against it.
MAX_GRAPH_DOCUMENTS = 6
MAX_GRAPH_CLIPS = 80

# link kind -> (label read from the target's side, label read from the source's side). Order is gravity: when
# two documents link the same pair of clips twice, the earlier kind wins.
LINK_KINDS = {
    "replaces": ("Replaced by", "Replaces"),
    "changes": ("Changed by", "Changes"),
    "supports": ("Supported by", "Supports"),
    "partly": ("Partly supported by", "Partly supports"),
    "contradicts": ("Contradicted by", "Contradicts"),
    "review": ("Needs review against", "Needs review against"),
}
ANSWER_KINDS = {
    "states": ("Quoted by", "Stated in"),
    "replaced": ("Quoted by", "Stated in a clause that was replaced:"),
    "conflicts": ("Quoted against", "Disagrees with"),
    "context": ("Quoted for context by", "Context from"),
    "notfound": ("Checked by", "Checked, does not say it:"),
}
CHECK_KINDS = {
    "replaces": ("Replaced by", "Replaces"),
    "changes": ("Changed by", "Changes"),
    "contradicts": ("Contradicted by", "Contradicts"),
    "partly": ("Partly supported by", "Partly supports"),
    "review": ("Needs review against", "Needs review against"),
    "supports": ("Supported by", "Supports"),
    "notmentioned": ("Not mentioned in", "Does not mention"),
}
CLAUSE_NO = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
CLIP_FIELDS = ("id", "section", "heading", "text", "kinds", "effect", "state", "parties", "commitments")

__all__ = ["ANSWER_KINDS", "CHECK_KINDS", "LINK_KINDS", "MAX_GRAPH_CLIPS", "MAX_GRAPH_DOCUMENTS", "answer_graph",
           "check_graph", "graph", "lane_order", "primary_document"]


def _long_date(iso: str) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{MONTHS[m - 1]} {d}, {y}"


def _changed(old_c: dict, new_c: dict) -> dict | None:
    """What an amendment changed in a clause, as the words to strike and the words that replace them: the
    deadline dates when both have one, else the first run of differing words (with its unit, "30 days")."""
    od, nd = old_c.get("deadline") or {}, new_c.get("deadline") or {}
    if od.get("date") and nd.get("date") and od["date"] != nd["date"]:
        return {"old": _long_date(od["date"]), "new": _long_date(nd["date"])}
    a, b = old_c["quote"]["quote"].split(), new_c["quote"]["quote"].split()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        old, new = a[i1:i2], b[j1:j2]
        if old and new and all(re.fullmatch(r"[\d.,%]+", w) for w in old + new) and i2 < len(a) and j2 < len(b):
            old, new = old + [a[i2]], new + [b[j2]]  # keep the unit: "30 days", "48 hours"
        strip = ".,;:"
        return {"old": " ".join(old).strip(strip), "new": " ".join(new).strip(strip)}
    return None


def primary_document(documents: list[dict]) -> dict | None:
    """The document the others are checked against: the one the engine classed as a contract, else the first."""
    return next((d for d in documents if d["type"] == "contract"), documents[0] if documents else None)


def lane_order(documents: list[dict]) -> list[dict]:
    """The primary document, then what amends it, then the rest in the order they were added."""
    primary = primary_document(documents)
    if primary is None:
        return []
    rest = [d for d in documents if d is not primary]
    return [primary] + [d for d in rest if d.get("amends_document_id") == primary["id"]] + \
        [d for d in rest if d.get("amends_document_id") != primary["id"]]


class _Clips:
    """Clips keyed "<lane key>-<section>" (or "-p<n>" for a passage without a section number)."""

    def __init__(self, session: Session, keys: dict[str, str]) -> None:
        self.session = session
        self.keys = keys  # document id -> lane key
        self.clips: dict[str, dict] = {}
        self._docs: dict[str, tuple[str, dict[str, tuple[int, dict]]]] = {}

    def _doc(self, doc_id: str) -> tuple[str, dict[str, tuple[int, dict]]]:
        if doc_id not in self._docs:
            d = self.session.document(doc_id)
            self._docs[doc_id] = (d["text"] or "", {p["id"]: (i, p) for i, p in enumerate(d["passages"])})
        return self._docs[doc_id]

    def find(self, span: dict | None) -> tuple[str, int, dict, str] | None:
        if not span or span.get("document_id") not in self.keys:
            return None
        text, passages = self._doc(span["document_id"])
        found = passages.get(span.get("passage_id") or "")
        if not found:
            return None
        idx, psg = found
        key = self.keys[span["document_id"]]
        section = span.get("section") or psg.get("section")
        cid = f"{key}-{section}" if section else f"{key}-p{idx + 1}"
        return cid, idx, psg, text

    def get(self, span: dict | None, kind: str | None = None, effect: str | None = None, create: bool = True) -> str | None:
        hit = self.find(span)
        if hit is None:
            return None
        cid, idx, psg, text = hit
        if cid not in self.clips:
            if not create:
                return None
            assert span is not None
            passage = CLAUSE_NO.sub("", text[psg["char_start"] : psg["char_end"]]).strip()
            self.clips[cid] = {"id": cid, "doc": self.keys[span["document_id"]],
                               "section": span.get("section") or psg.get("section") or f"¶{idx + 1}",
                               "heading": psg["title"], "text": passage, "kinds": [], "effect": "evidence",
                               "order": psg["char_start"], "parties": [], "commitments": [], "review": False}
        c = self.clips[cid]
        if kind and kind not in c["kinds"]:
            c["kinds"].append(kind)
        if effect and c["effect"] != "replaced":
            c["effect"] = effect
        return cid

    def commitment(self, cmt: dict, create: bool = True) -> str | None:
        cid = self.get(cmt["quote"], cmt["type"], cmt["document_effect"], create=create)
        if cid:
            c = self.clips[cid]
            party = cmt.get("obliging_party")
            if party and party not in c["parties"]:
                c["parties"].append(party)
            c["commitments"].append(cmt["id"])
            c["review"] = c["review"] or bool(cmt.get("needs_review"))
        return cid

    def lanes(self, spec: list[tuple[dict, str, str]], keep: set[str] | None = None) -> list[dict]:
        out = []
        for d, key, name in spec:
            cs = sorted((c for c in self.clips.values() if c["doc"] == key and (keep is None or c["id"] in keep)),
                        key=lambda c: c["order"])
            out.append({"key": key, "name": name, "title": d["title"], "file": d.get("filename"), "type": d["type"],
                        "document_id": d["id"], "clips": [_public(c) for c in cs]})
        return out


def _public(c: dict) -> dict:
    out = {k: c[k] for k in CLIP_FIELDS if k in c}
    out["state"] = c.get("state") or _state(c)
    for k in ("node", "status"):
        if k in c:
            out[k] = c[k]
    return out


def _state(c: dict) -> str:
    if c["effect"] in ("replaced", "deleted"):
        return "replaced"
    if c.get("review"):
        return "review"
    return c["effect"]


def _cap(clips: dict[str, dict], links: list[dict], lane_rank: dict[str, int], limit: int,
         rank: dict[str, int] | None = None, fixed: frozenset[str] = frozenset()) -> tuple[set[str], list[dict]]:
    """Keep at most `limit` clips: linked clips first (in `rank` order when given, else lane order), then the
    rest in lane order. Links that lose an end are dropped with it; `fixed` ids (the answer node, the "not
    mentioned" node) are not clips and always stay."""
    if len(clips) <= limit:
        return set(clips), links
    linked = {lk["from"] for lk in links} | {lk["to"] for lk in links}

    def key(c: dict) -> tuple:
        return (c["id"] not in linked, (rank or {}).get(c["id"], 0), lane_rank.get(c["doc"], 99), c["order"])

    keep = {c["id"] for c in sorted(clips.values(), key=key)[:limit]}
    ends = keep | fixed
    return keep, [lk for lk in links if lk["from"] in ends and lk["to"] in ends]


def _kinds(table: dict[str, tuple[str, str]]) -> dict[str, dict[str, str]]:
    return {k: {"in": a, "out": b} for k, (a, b) in table.items()}


# ---------------------------------------------------------------------------------- the workspace
def graph(session: Session, lanes: list[tuple[str, str, str]] | None = None,
          max_documents: int = MAX_GRAPH_DOCUMENTS, max_clips: int = MAX_GRAPH_CLIPS) -> dict[str, Any]:
    """Every document as a lane (``lanes`` = [(document id, key, name)] fixes their order and names; by default
    the primary document first, then the rest in the order added, keyed d1, d2, ... and named by title), every
    commitment as a clip, and the links between clips."""
    reg = session.register()
    docs = {d["id"]: d for d in reg["documents"]}
    if lanes is None:
        lanes = [(d["id"], f"d{i + 1}", d["title"]) for i, d in enumerate(lane_order(reg["documents"]))]
    spec = [(docs[i], k, n) for i, k, n in lanes][:max_documents]
    keys = {d["id"]: k for d, k, _n in spec}
    clips = _Clips(session, keys)
    by_cmt = {c["id"]: c for c in reg["commitments"]}

    for c in reg["commitments"]:
        clips.commitment(c)

    links: dict[tuple[str, str], dict] = {}
    changes: dict[str, dict] = {}
    gravity = list(LINK_KINDS)

    def link(kind: str, src: str | None, dst: str | None, note: str, severity: str) -> None:
        if not src or not dst or src == dst:
            return
        prev = links.get((src, dst))
        if prev and gravity.index(prev["kind"]) <= gravity.index(kind):
            return
        links[(src, dst)] = {"kind": kind, "from": src, "to": dst, "note": note, "severity": severity}

    for c in reg["commitments"]:  # the register: supersede edges, with what changed
        for r in c["replaced_by"]:
            new = by_cmt[r["id"]]
            src, dst = clips.get(new["quote"]), clips.get(c["quote"])
            if not src or not dst:
                continue
            diff = _changed(c, new)
            if diff:
                changes[dst] = {**diff, "by": src}
            link("replaces", src, dst, "", "high")

    base = spec[0][0]["id"] if spec else None
    for other, _k, _n in spec[1:]:
        run = session.verify(base, other["id"])
        for f in run["findings"]:
            if f["routine"] or not f["subject_span"]:
                continue
            dst = clips.get(f["subject_span"])
            if not dst:
                continue
            v = f["verdict"]
            subject = by_cmt.get(f["subject_id"])
            for sp in f["supporting"]:
                if sp:
                    link("supports" if v == "consistent" else "partly", clips.get(sp), dst, f["explanation"], f["severity"])
            for sp in f["conflicting"]:
                if not sp:
                    continue
                if other["type"] == "amendment":
                    kind = "replaces" if subject and subject["document_effect"] == "replaced" else "changes"
                else:
                    kind = {"contradicted": "contradicts", "partially_supported": "partly"}.get(v, "review")
                src = clips.get(sp)
                if not src:
                    continue
                prev = links.get((src, dst))
                link(kind, src, dst, f["explanation"], f["severity"])
                if prev and prev["kind"] == kind and not prev["note"]:
                    links[(src, dst)]["note"] = f["explanation"]

    lane_rank = {k: i for i, (_d, k, _n) in enumerate(spec)}
    keep, kept_links = _cap(clips.clips, list(links.values()), lane_rank, max_clips)
    out_lanes = clips.lanes(spec, keep)
    order = {c["id"]: i for i, c in enumerate(c for lane in out_lanes for c in lane["clips"])}
    kept_links.sort(key=lambda lk: (order[lk["to"]], order[lk["from"]]))
    return {
        "view": "register",
        "kinds": _kinds(LINK_KINDS),
        "lanes": out_lanes,
        "links": kept_links,
        "changes": {k: v for k, v in changes.items() if k in keep and v["by"] in keep},
        "primary": base,
        "shown": {"documents": [len(spec), len(docs)], "clips": [len(keep), len(clips.clips)]},
    }


# ---------------------------------------------------------------------------------- an answer
def answer_graph(session: Session, answer: dict, max_clips: int = MAX_GRAPH_CLIPS) -> dict[str, Any]:
    """The answer as a node above the documents it cites; each cited clause linked to it by its relation."""
    reg = session.register()
    cited = {c["span"]["document_id"] for c in answer.get("citations", []) if c.get("span")}
    spec = [(d, f"d{i + 1}", d["title"]) for i, d in enumerate(lane_order(reg["documents"])) if d["id"] in cited]
    clips = _Clips(session, {d["id"]: k for d, k, _n in spec})
    links: list[dict] = []
    seen: set[str] = set()
    for cit in answer.get("citations", []):
        cid = clips.get(cit.get("span"))
        if cid and cid not in seen:
            seen.add(cid)
            links.append({"kind": cit.get("role") or "supports", "from": "answer", "to": cid,
                          "note": cit.get("note") or "", "severity": "info"})
    for c in reg["commitments"]:  # what the engine knows about the cited clauses (replaced, who must act)
        clips.commitment(c, create=False)
    for lk in links:
        role, clip = lk["kind"], clips.clips[lk["to"]]
        if role == "conflicts":
            lk["kind"] = "conflicts"
        elif role == "checked_not_supporting":
            lk["kind"] = "notfound"
        elif role == "context":
            lk["kind"] = "context"
        else:
            lk["kind"] = "replaced" if _state(clip) == "replaced" else "states"
    keep, links = _cap(clips.clips, links, {k: i for i, (_d, k, _n) in enumerate(spec)}, max_clips,
                       fixed=frozenset({"answer"}))
    node = {"id": "answer", "section": "", "heading": "", "text": answer.get("answer_text") or "", "kinds": [],
            "effect": "answer", "state": "answer", "parties": [], "commitments": [], "node": "answer",
            "status": answer.get("status") or "not_addressed"}
    answer_lane = {"key": "answer", "name": "Answer", "title": "Answer", "file": None, "type": "answer",
                   "document_id": None, "clips": [node]}
    return {
        "view": "answer",
        "kinds": _kinds(ANSWER_KINDS),
        "lanes": [answer_lane, *clips.lanes(spec, keep)],
        "links": links,
        "question": answer.get("question") or "",
        "shown": {"documents": [len(spec), len(spec)], "clips": [len(keep), len(clips.clips)]},
    }


# ---------------------------------------------------------------------------------- a check
VERDICT_KIND = {"consistent": "supports", "partially_supported": "partly", "contradicted": "contradicts",
                "ambiguous": "review", "needs_human_review": "review", "not_addressed": "notmentioned"}


def check_graph(session: Session, run: dict, max_clips: int = MAX_GRAPH_CLIPS) -> dict[str, Any]:
    """Two lanes, the checked document and the other; each finding a link carrying its index in run["findings"].
    A commitment the other document never mentions links to that lane's "not mentioned" node."""
    reg = session.register()
    docs = {d["id"]: d for d in reg["documents"]}
    base, other = docs[run["base_document_id"]], docs[run["other_document_id"]]
    spec = [(base, "base", base["title"]), (other, "other", other["title"])]
    clips = _Clips(session, {base["id"]: "base", other["id"]: "other"})
    absent_id = "other-absent"
    links: list[dict] = []
    rank: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()

    def add(kind: str, src: str | None, dst: str, f: dict, i: int) -> None:
        if not src or src == dst or (src, dst) in seen:
            return
        seen.add((src, dst))
        rank.setdefault(dst, i)
        rank.setdefault(src, i)
        links.append({"kind": kind, "from": src, "to": dst, "note": f["explanation"], "severity": f["severity"],
                      "finding": i})

    by_cmt = {c["id"]: c for c in reg["commitments"]}
    for i, f in enumerate(run["findings"]):
        dst = clips.get(f["subject_span"]) if f.get("subject_span") else None
        if not dst:
            continue
        kind = VERDICT_KIND.get(f["verdict"], "review")
        spans = [s for s in f.get("conflicting") or [] if s]
        if spans:
            if run.get("mode") == "amendment":
                subject = by_cmt.get(f.get("subject_id") or "")
                ckind = "replaces" if subject and subject["document_effect"] != "in_force" else "changes"
            else:
                ckind = kind
            if ckind in ("supports", "notmentioned"):
                ckind = "review"
            for s in spans:
                add(ckind, clips.get(s), dst, f, i)
        for s in [s for s in f.get("supporting") or [] if s]:
            add("supports" if kind == "supports" else "partly", clips.get(s), dst, f, i)
        if not spans and not any(f.get("supporting") or []):
            if kind == "notmentioned":
                add("notmentioned", absent_id, dst, f, i)
    for c in reg["commitments"]:
        clips.commitment(c, create=False)
    real = dict(clips.clips)
    keep, links = _cap(real, links, {"base": 0, "other": 1}, max_clips, rank, fixed=frozenset({absent_id}))
    lanes_out = clips.lanes(spec, keep)
    if any(lk["from"] == absent_id for lk in links):
        lanes_out[1]["clips"].append({"id": absent_id, "section": "", "heading": "", "text": "", "kinds": [],
                                      "effect": "absent", "state": "absent", "parties": [], "commitments": [],
                                      "node": "absent"})
    return {
        "view": "check",
        "kinds": _kinds(CHECK_KINDS),
        "lanes": lanes_out,
        "links": links,
        "mode": run.get("mode"),
        "shown": {"documents": [2, 2], "clips": [len(keep), len(real)]},
    }
