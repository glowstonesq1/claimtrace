"""Evidence page data (scripts/build_site_data.py -> apps/site/data, apps/site/evidence/index.html).

The holdout set must stay sealed: nothing from its cases (ids, documents, questions, gold labels, descriptions) or
from the holdout runs' per-case outputs may reach the site. Only aggregates are allowed."""

from __future__ import annotations

import functools
import hashlib
import html
import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "apps" / "site"
HOLDOUT = ROOT / "evals" / "datasets" / "holdout"
OPEN_SETS = [ROOT / "evals" / "datasets" / "core", ROOT / "evals" / "datasets" / "amendments-v2"]
RUNS = ROOT / "evals" / "runs" / "published"
NUMBER_WORDS = {w: str(n) for n, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen twenty".split())}
NUMBER_WORDS.update({w: str(n) for n, w in zip(range(30, 100, 10), "thirty forty fifty sixty seventy eighty ninety".split(),
                                               strict=True)})
NUMBER_WORDS_REV = {v: k for k, v in NUMBER_WORDS.items()}
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


def _site_pages(site: Path) -> list[Path]:
    """Every HTML page of the site (home, evidence, get, docs, try, 404, partials), but not the try page's
    self-hosted Pyodide bundle, which is third-party code."""
    return sorted(p for p in site.rglob("*.html") if "pyodide" not in p.relative_to(site).parts)


def _published_text(site: Path = SITE) -> str:
    files = sorted((site / "data").rglob("*")) + sorted((site / "evidence").glob("*")) + _site_pages(site)
    text = "\n".join(p.read_text(encoding="utf-8") for p in files if p.is_file())
    # compare in the same escaping the outputs use: raw, JSON-escaped and HTML-escaped
    return text


def _norm(s: str) -> str:
    """Compare text, not formatting: HTML entities decoded, JSON escapes undone, case, punctuation and spacing
    dropped, and number words written as digits ("thirty" -> "30")."""
    s = html.unescape(s.replace("\\n", " ").replace('\\"', '"')).lower()
    return " ".join(NUMBER_WORDS.get(w, w) for w in re.findall(r"\w+", s))


NGRAM = 8  # a run of 8 words from a sealed field is enough to call it copied


def _ngrams(normed: str) -> set[tuple[str, ...]]:
    w = normed.split()
    return {tuple(w[i : i + NGRAM]) for i in range(len(w) - NGRAM + 1)}


def _short_hash(s: str) -> str:
    return hashlib.sha256(_norm(s).encode()).hexdigest()[:10]


@functools.cache
def _open_strings() -> frozenset[str]:
    open_strings: set[str] = set()
    for c in _jsonl([p for d in OPEN_SETS for p in sorted(d.glob("*.jsonl"))]):
        open_strings |= _strings(c)
    open_runs = [d for d in RUNS.iterdir() if "holdout" not in d.name]
    for c in _jsonl([d / "cases.jsonl" for d in open_runs]):
        open_strings |= _strings(c)
    return frozenset(open_strings)


@functools.cache
def _sealed_strings() -> tuple[set[str], set[str]]:
    holdout_cases = _jsonl(sorted(HOLDOUT.glob("*.jsonl")))
    open_corpus = "\n".join(sorted(_norm(s) for s in _open_strings()))

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


@functools.cache
def _open_ngrams() -> frozenset[tuple[str, ...]]:
    grams: set[tuple[str, ...]] = set()
    for s in _open_strings():
        grams |= _ngrams(_norm(s))
    return frozenset(grams)


def _find_leaks(published_raw: str, ids: set[str], sealed: set[str]) -> tuple[list[str], list[str]]:
    """(leaked ids, leaked strings) of the sealed set found in the published text: a sealed string whose
    normalised text appears whole, or any of whose 8-word runs (fields of 8 words or more; runs that also occur
    in the public sets do not count) appears on the site."""
    raw_lower = html.unescape(published_raw).lower()
    leaked_ids = sorted(i for i in ids if re.search(rf"(?<![\w-]){re.escape(i.lower())}(?![\w-])", raw_lower))
    published = _norm(published_raw)
    published_grams = _ngrams(published)
    open_grams = _open_ngrams()
    leaked = []
    for s in sealed:
        n = _norm(s)
        if f" {n} " in f" {published} " or (_ngrams(n) - open_grams) & published_grams:
            leaked.append(s)
    return leaked_ids, sorted(leaked)


def _leak_report(leaked_ids: list[str], leaked: list[str]) -> str:
    """Counts and short hashes only: this message is printed in public CI logs."""
    return (f"{len(leaked_ids)} holdout case id(s) and {len(leaked)} holdout string(s) on the site; "
            f"sha256[:10] of the normalised strings: {sorted(_short_hash(x) for x in leaked_ids + leaked)[:10]}. "
            "Find them locally with a script that compares hashes; do not print the text.")


def test_no_holdout_case_content_reaches_the_site() -> None:
    ids, sealed = _sealed_strings()
    if not (len(ids) == 46 and len(sealed) > 300):  # not an assert: its introspection would print the sets
        pytest.fail(f"the sealing test lost its inputs ({len(ids)} ids, {len(sealed)} strings)", pytrace=False)
    leaked_ids, leaked = _find_leaks(_published_text(), ids, sealed)
    if leaked_ids or leaked:
        pytest.fail(_leak_report(leaked_ids, leaked), pytrace=False)


def _derived_sentence(sealed: set[str]) -> tuple[str, str]:
    """A long sealed sentence (chosen at runtime, never written down) and a near-copy of it: one word changed, a
    number spelled out, punctuation and spacing altered."""
    candidates = sorted((s for s in sealed if len(s.split()) >= 20 and re.search(r"\b\d{1,2}\b", s)
                         and not re.search(r"[.;:!?]\s|\n", s.strip())), key=len)
    norm = {x: _norm(x) for x in sealed}
    # one that contains no other sealed string, so only matching of the sentence itself can catch the copy
    original = next((c for c in candidates if not any(x != c and norm[x] in norm[c] for x in sealed)), None)
    if original is None:
        pytest.fail("no long sealed sentence with a number to derive from", pytrace=False)
    words = original.split()
    middle = len(words) // 2
    words[middle] = "zzzaltered"
    near = " ".join(words)
    near = re.sub(r"\b(\d{1,2})\b", lambda m: NUMBER_WORDS_REV.get(m.group(1), m.group(1)), near)  # 30 -> thirty
    return original, near.replace(",", " ,").upper()


@pytest.mark.parametrize("planted", ["evidence/index.html", "index.html", "get/index.html"])
def test_sealing_check_catches_a_near_copy(tmp_path: Path, planted: str) -> None:
    ids, sealed = _sealed_strings()
    original, near = _derived_sentence(sealed)
    if near == original:
        pytest.fail("the derived sentence is unchanged", pytrace=False)
    site = tmp_path / "site"
    shutil.copytree(SITE, site, ignore=shutil.ignore_patterns("pyodide", "media", "fonts", "vendor"))
    page = site / planted
    page.write_text(page.read_text(encoding="utf-8") + f"\n<p>{html.escape(near)}</p>\n", encoding="utf-8")
    leaked_ids, leaked = _find_leaks(_published_text(site), ids, sealed)
    found = bool(leaked_ids or leaked)
    del original, near  # nothing below may show them
    if not found:
        pytest.fail("a near-copy of a sealed sentence on the page was not detected", pytrace=False)


def test_leak_report_shows_no_sealed_text() -> None:
    ids, sealed = _sealed_strings()
    sample = sorted(sealed, key=len)[-3:]
    some_ids = sorted(ids)[:2]
    report = _leak_report(some_ids, sample)
    shown = sum(1 for x in [*sample, *some_ids] if x in report or _norm(x)[:40] in _norm(report))
    if shown:  # pytest.fail, not assert: assertion rewriting would print the values
        pytest.fail(f"the failure message would print {shown} sealed value(s)", pytrace=False)


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


# ------------------------------------------------------------------ home page: hero panel and evidence map
SAMPLES = ROOT / "examples" / "documents"


def _sample_text() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in SAMPLES.glob("*.md")}


def test_samples_json_is_the_engine_output_on_the_samples() -> None:
    """apps/site/data/samples.json equals a fresh run of the rules engine on examples/documents."""
    published = json.loads((SITE / "data" / "samples.json").read_text(encoding="utf-8"))
    assert published == _load_builder().build_samples()


def test_hero_clause_2_1_is_replaced_by_amendment_1_1_with_verbatim_quotes() -> None:
    data = json.loads((SITE / "data" / "samples.json").read_text(encoding="utf-8"))
    lead = data["hero"]["rows"][0]
    assert (lead["clip"], lead["kind"], lead["by"]) == ("msa-2.1", "replaces", "amd-1.1")
    assert lead["change"] == {"old": "March 31, 2026", "new": "May 15, 2026"}
    clips = {c["id"]: (lane, c) for lane in data["lanes"] for c in lane["clips"]}
    texts = _sample_text()
    for cid, words in (("msa-2.1", "March 31, 2026"), ("amd-1.1", "May 15, 2026")):
        lane, c = clips[cid]
        assert words in c["text"] and c["text"] in texts[lane["file"]], cid
    assert clips["amd-1.1"][1]["section"] == "1.1" and clips["amd-1.1"][0]["name"] == "Amendment No. 1"
    page = (SITE / "index.html").read_text(encoding="utf-8")
    hero = page.split("<!-- build:hero -->")[1].split("<!-- /build:hero -->")[0]
    assert "<del>March 31, 2026</del>" in hero and "<ins>May 15, 2026</ins>" in hero
    assert "Amendment No. 1 §1.1" in hero and "docs/img" not in page


def test_every_map_clip_is_verbatim_and_every_link_joins_two_clips() -> None:
    data = json.loads((SITE / "data" / "samples.json").read_text(encoding="utf-8"))
    texts = _sample_text()
    assert [lane["file"] for lane in data["lanes"]] == ["msa-v1.md", "amendment-1.md", "audit-report-2026.md",
                                                        "delivery-record.md"]
    ids = set()
    for lane in data["lanes"]:
        for c in lane["clips"]:
            ids.add(c["id"])
            if c.get("withheld"):
                assert c["text"] == "", c["id"]
                continue
            assert f"{c['section']} {c['text']}" in texts[lane["file"]], c["id"]
    builder = _load_builder()
    assert {c["id"] for lane in data["lanes"] for c in lane["clips"] if c.get("withheld")} == set(builder.WITHHELD_CLIPS)
    kinds = {lk["kind"] for lk in data["links"]}
    assert {"replaces", "supports", "contradicts"} <= kinds <= set(data["kinds"])
    for lk in data["links"]:
        assert lk["from"] in ids and lk["to"] in ids, lk
    page = (SITE / "index.html").read_text(encoding="utf-8")
    assert {f'data-clip="{i}"' for i in ids} == set(re.findall(r'data-clip="[^"]+"', page))
    assert data["integrity"]["verified"] == data["integrity"]["quotes"]


def test_home_numbers_match_the_published_runs() -> None:
    """The home page's numbers are the docs/evaluation.md headline values (v0.2, sealed sets)."""
    page = (SITE / "index.html").read_text(encoding="utf-8")
    nums = page.split("<!-- build:numbers -->")[1].split("<!-- /build:numbers -->")[0]
    values = re.findall(r'<td class="num nums__v">([0-9.]+)', nums)
    assert values == ["0.00", "0.03", "0.71", "0.81", "0.60", "0.71"]
    assert "0.51 to 0.70, n=105" in nums and "0.62 to 0.80, n=91" in nums and "precision 0.83" in nums
    evaluation = (ROOT / "docs" / "evaluation.md").read_text(encoding="utf-8")
    assert "**0.60 (0.51–0.70)** n=105" in evaluation and "**0.71 (0.62–0.80)** n=91" in evaluation
    assert "**0.83 / 0.71**" in evaluation


def test_withheld_clauses_point_to_try_and_say_nothing_about_test_cases() -> None:
    """A withheld clause's panel says only that the wording is on Try it, with a link; no word about evaluation."""
    builder = _load_builder()
    samples = builder.build_samples()
    script = (SITE / "map.js").read_text(encoding="utf-8")
    words = "Wording not shown on this page. Read it on "
    tail = ", where the full sample contract is loaded."
    for cid in builder.WITHHELD_CLIPS:
        panel = builder.render_panel(samples, cid)
        assert f'{words}<a href="try/">Try it</a>{tail}' in panel, cid
    assert words in script and tail in script and "go.href = 'try/'" in script
    for text in (script, (SITE / "index.html").read_text(encoding="utf-8")):
        assert not re.search(r"sealed test|test case|evaluation case", text, re.I)
