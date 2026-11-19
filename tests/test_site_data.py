"""Evidence page data (scripts/build_site_data.py -> apps/site/data, apps/site/evidence/index.html).

The holdout set must stay sealed: nothing from its cases (ids, documents, questions, gold labels, descriptions) or
from the holdout runs' per-case outputs may reach the site. Only aggregates are allowed."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "apps" / "site"
HOLDOUT = ROOT / "evals" / "datasets" / "holdout"
OPEN_SETS = [ROOT / "evals" / "datasets" / "core", ROOT / "evals" / "datasets" / "amendments-v2"]
RUNS = ROOT / "evals" / "runs" / "published"
MIN_LEN = 16  # shorter strings ("Supplier", "contradicted") are vocabulary, not case content


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_site_data", ROOT / "scripts" / "build_site_data.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _strings(obj: object) -> set[str]:
    out: set[str] = set()
    if isinstance(obj, str):
        out.add(obj)
        # documents are long: also check every line and sentence on its own
        out.update(x.strip() for x in re.split(r"\n+|(?<=[.;:])\s+", obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _strings(v)
    return out


def _jsonl(paths: list[Path]) -> list[dict]:
    return [json.loads(line) for p in paths for line in p.read_text().splitlines() if line.strip()]


def _published_text() -> str:
    files = sorted((SITE / "data").rglob("*")) + sorted((SITE / "evidence").glob("*"))
    text = "\n".join(p.read_text(encoding="utf-8") for p in files if p.is_file())
    # compare in the same escaping the outputs use: raw, JSON-escaped and HTML-escaped
    return text


def _norm(s: str) -> str:
    return re.sub(
        r"\s+", " ", s.replace("&quot;", '"').replace("&#x27;", "'").replace("&amp;", "&").replace("\\n", " ").replace('\\"', '"')
    ).lower()


def _sealed_strings() -> tuple[set[str], set[str]]:
    holdout_cases = _jsonl(sorted(HOLDOUT.glob("*.jsonl")))
    open_strings: set[str] = set()
    for c in _jsonl([p for d in OPEN_SETS for p in sorted(d.glob("*.jsonl"))]):
        open_strings |= _strings(c)
    open_runs = [d for d in RUNS.iterdir() if "holdout" not in d.name]
    for c in _jsonl([d / "cases.jsonl" for d in open_runs]):
        open_strings |= _strings(c)
    open_corpus = "\n".join(sorted(_norm(s) for s in open_strings))

    ids = {c["id"] for c in holdout_cases}
    content: set[str] = set()
    for c in holdout_cases:
        content |= _strings({k: v for k, v in c.items() if k not in ("suite",)})
    for d in RUNS.iterdir():
        if "holdout" in d.name:
            content |= _strings(_jsonl([d / "cases.jsonl"]))
    # a phrase that also occurs in the public sets (e.g. "within 30 days of") proves nothing either way
    sealed = {s for s in content if len(s.strip()) >= MIN_LEN and _norm(s) not in open_corpus}
    return ids, sealed


def test_site_data_is_up_to_date() -> None:
    builder = _load_builder()
    stale = [
        str(p.relative_to(ROOT)) for p, text in builder.build().items() if not p.exists() or p.read_text(encoding="utf-8") != text
    ]
    assert not stale, f"run python scripts/build_site_data.py; stale: {stale}"


def test_no_holdout_case_content_reaches_the_site() -> None:
    ids, sealed = _sealed_strings()
    assert len(ids) == 46 and len(sealed) > 300, "the sealing test lost its inputs"
    published = _norm(_published_text())
    leaked_ids = sorted(i for i in ids if re.search(rf"(?<![\w-]){re.escape(i.lower())}(?![\w-])", published))
    assert not leaked_ids, f"holdout case ids on the site: {leaked_ids[:5]}"
    leaked = sorted(s for s in sealed if _norm(s) in published)
    assert not leaked, f"{len(leaked)} holdout strings on the site, e.g. {leaked[:3]}"


def test_holdout_runs_are_aggregates_only() -> None:
    summary = json.loads((SITE / "data" / "summary.json").read_text())
    cases = json.loads((SITE / "data" / "cases.json").read_text())
    holdout_runs = {r["id"] for r in summary["runs"] if r["set"] == "holdout"}
    assert holdout_runs == {
        "v1-holdout-rules",
        "v1-holdout-keyword",
        "v2-holdout-rules",
        "v2-holdout-keyword",
        "v2-postfix-holdout-rules",
    }
    assert not holdout_runs & set(cases["results"]), "per-case results published for a holdout run"
    assert all(c["set"] in ("core", "amendments-v2") for c in cases["cases"])
    assert {r["set"] for r in cases["runs"]} == {"core", "amendments-v2"}


def test_manifests_carry_reproduction_details() -> None:
    summary = json.loads((SITE / "data" / "summary.json").read_text())
    for r in summary["runs"]:
        man = json.loads((RUNS / r["id"] / "manifest.json").read_text())
        assert r["manifest"]["dataset_sha256"] == man["dataset_sha256"]
        assert r["manifest"]["git_commit"] == man["git_commit"]
        assert r["dataset_hash_matches"], f"{r['id']}: dataset changed since it was scored"


def test_headline_numbers_match_the_published_runs() -> None:
    summary = json.loads((SITE / "data" / "summary.json").read_text())
    runs = {r["id"]: r for r in summary["runs"]}
    am = runs["v2-amendments-v2-rules"]["metrics"]["verification_accuracy_amendment"]
    assert (am["v"], am["n"], am["ci"]) == (0.6, 105, [0.505, 0.695])
    assert runs["v2-holdout-rules"]["metrics"]["hallucination_rate"]["v"] == 0.0
    page = (SITE / "evidence" / "index.html").read_text()
    assert "Wrong 4 in 10" in page and ">0.60<" in page


def test_wilson_interval() -> None:
    w = _load_builder().wilson
    assert w(0, 8) == [0.0, 0.324]
    assert w(2, 63) == [0.009, 0.109]
