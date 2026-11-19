#!/usr/bin/env python3
"""Build the data behind the site's Evidence page (apps/site/evidence/) from the published eval runs.

    python scripts/build_site_data.py           # write apps/site/data/** and the static parts of the page
    python scripts/build_site_data.py --check   # exit 1 if anything on disk differs from a fresh build

Reads evals/runs/published/*/{manifest,summary,cases}.jsonl and evals/datasets/<set>/*.jsonl. Standard library
only and deterministic: the same inputs always give byte-identical outputs (CI rebuilds and diffs).

Sealing rule. The holdout set (runs on dataset ``holdout``: v1-holdout-*, v2-holdout-*, v2-postfix-holdout-*)
must stay sealed, so for it only the published aggregates in summary.json and the manifest are emitted: no case
ids, no document text, no questions, no gold labels, no system outputs. Its cases.jsonl and dataset files are
never opened here. Core and amendments-v2 (spent in v0.2) cases are emitted in full.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "evals" / "runs" / "published"
DATASETS = ROOT / "evals" / "datasets"
SITE = ROOT / "apps" / "site"
OUT = SITE / "data"
PAGE = SITE / "evidence" / "index.html"
REPO = "https://github.com/glowstonesq1/claimtrace"

SEALED = {"holdout"}
SETS = {
    "holdout": {
        "label": "Holdout",
        "long": "Holdout set (sealed, 46 cases)",
        "about": "Never opened while tuning. Totals only: the cases stay sealed.",
    },
    "amendments-v2": {
        "label": "Amendments",
        "long": "Amendments set (sealed for v0.2, now spent, 50 cases)",
        "about": "Scored once for v0.2, now spent. Every case is published below.",
    },
    "core": {
        "label": "Core",
        "long": "Core set (used for tuning, 140 cases)",
        "about": "Used for tuning, so it shows coverage, not generalisation. Every case is published below.",
    },
}
SET_ORDER = ["holdout", "amendments-v2", "core"]
SUITES = ["extraction", "deadline", "consistency", "contradiction", "qa", "evidence_gap", "amendment", "ambiguous"]
SUITE_LABELS = {
    "extraction": "Extraction",
    "deadline": "Deadlines",
    "consistency": "Consistency",
    "contradiction": "Contradiction",
    "qa": "Questions",
    "evidence_gap": "Evidence gap",
    "amendment": "Amendments",
    "ambiguous": "Ambiguous wording",
}

# (key, label, plain sentence, lower_is_better)
METRICS = [
    (
        "hallucination_rate",
        "Hallucination rate",
        "Questions answered with an unverifiable quote, or answered when the documents say nothing",
        True,
    ),
    (
        "false_clear_rate",
        "False-clear rate",
        "Checks called consistent when the other document contradicts or only partly supports them",
        True,
    ),
    (
        "verification_accuracy_amendment",
        "Amendment verdicts",
        "Did it say correctly whether the amendment changed each clause?",
        False,
    ),
    ("amendment_effect_accuracy", "Amendment effects", "Replaced, deleted or still in force, per section", False),
    ("contradiction_recall", "Contradiction recall", "Share of real contradictions it found", False),
    ("contradiction_precision", "Contradiction precision", "Share of its contradiction findings that were real", False),
    ("verification_accuracy_contradiction", "Contradiction suite", "Verdict accuracy on the contradiction cases", False),
    (
        "verification_accuracy_consistency",
        "Consistency suite",
        "Verdict accuracy where most checks really are consistent, so always saying consistent scores well",
        False,
    ),
    (
        "verification_accuracy_evidence_gap",
        "Evidence-gap suite",
        "Contract against audit report: tested, not tested, or failed",
        False,
    ),
    ("qa_status_accuracy", "Question answering", "Stated, contradicted, not addressed and so on, per question", False),
    ("not_found_recall", "Says “not found” when it should", "Questions the documents do not answer", False),
    ("citation_recall", "Citation recall", "Gold quotes it cited, on questions that have them", False),
    ("commitment_recall", "Commitment recall", "Labelled commitments it extracted", False),
    ("commitment_precision", "Commitment precision", "Extracted commitments that were labelled", False),
    ("party_attribution_accuracy", "Who owes it", "Obliging party right, on matched commitments", False),
    ("deadline_accuracy", "Deadlines", "Deadline kind and value right", False),
    ("ambiguity_flag_accuracy", "Flags vague wording", "Vague clauses flagged for review at low confidence", False),
]
METRIC_KEYS = [m[0] for m in METRICS]


# ------------------------------------------------------------------ reading
def _read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _read_jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def dataset_hash(name: str) -> str:
    """Same definition as packages/evaluation/runner.py: sha256 over the set's *.jsonl files in name order."""
    h = hashlib.sha256()
    for f in sorted((DATASETS / name).glob("*.jsonl")):
        h.update(f.read_bytes())
    return h.hexdigest()


def version_of(run: str) -> tuple[str, str, int]:
    """(version id, label, sort order) from the run directory name."""
    if run.startswith("v1-blind-baseline"):
        return "v0.1-blind", "v0.1 blind", 0
    if run.startswith("v2-postfix-"):
        return "v0.2-postfix", "v0.2 post-fix", 3
    if run.startswith("v2-"):
        return "v0.2", "v0.2", 2
    return "v0.1", "v0.1", 1


def system_label(system: str) -> str:
    return "Rules" if system == "rules" else "Keyword floor"


# ------------------------------------------------------------------ statistics
def wilson(x: int, n: int, z: float = 1.959964) -> list[float]:
    if n <= 0:
        return [0.0, 0.0]
    p = x / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round(max(0.0, (c - r) / d), 3), round(min(1.0, (c + r) / d), 3)]


def metric_point(summary: dict, key: str) -> dict | None:
    """value, interval, n, method. Bootstrap CI when the run published one, else a Wilson interval from counts
    recovered from the published aggregate (value x n), never from case files."""
    if key in ("contradiction_recall", "contradiction_precision"):
        cd = summary.get("contradiction_detection")
        if not cd:
            return None
        n_gold = cd["n_gold_contradictions"]
        tp = round((cd["recall"] or 0) * n_gold)
        if key == "contradiction_recall":
            return {"v": cd["recall"], "ci": wilson(tp, n_gold), "n": n_gold, "x": tp, "m": "wilson"}
        if cd["precision"] is None:
            return {"v": None, "ci": None, "n": 0, "x": 0, "m": None, "note": "no contradictions predicted"}
        n_pred = round(tp / cd["precision"]) if cd["precision"] else 0
        return {"v": cd["precision"], "ci": wilson(tp, n_pred), "n": n_pred, "x": tp, "m": "wilson"}
    m = summary.get(key)
    if not m or m.get("value") is None:
        return None
    out = {"v": m["value"], "n": m["n"]}
    if "ci95" in m:
        out.update(ci=list(m["ci95"]), m="bootstrap")
    else:
        x = round(m["value"] * m["n"])
        out.update(ci=wilson(x, m["n"]), x=x, m="wilson")
    return out


# ------------------------------------------------------------------ runs
def load_runs() -> list[dict]:
    runs = []
    for d in sorted(p for p in RUNS.iterdir() if p.is_dir()):
        man = _read_json(d / "manifest.json")
        summ = _read_json(d / "summary.json")
        vid, vlabel, vorder = version_of(d.name)
        ds = man["suite"]
        runs.append(
            {
                "id": d.name,
                "set": ds,
                "system": man["system"],
                "version": vid,
                "version_label": vlabel,
                "order": vorder,
                "label": f"{system_label(man['system'])} {vlabel}",
                "sealed": ds in SEALED,
                "manifest": {
                    "git_commit": man.get("git_commit"),
                    "dataset_sha256": man["dataset_sha256"],
                    "timestamp": man.get("timestamp"),
                    "claimtrace_version": man.get("claimtrace_version"),
                    "extractor_version": man.get("extractor_version"),
                    "python": man.get("python"),
                },
                "dataset_hash_matches": dataset_hash(ds) == man["dataset_sha256"],
                "cases": summ.get("cases", {}),
                "metrics": {k: p for k in METRIC_KEYS if (p := metric_point(summ, k)) is not None},
                "_dir": d,
            }
        )
    runs.sort(key=lambda r: (SET_ORDER.index(r["set"]), r["system"] != "rules", r["order"]))
    return runs


# ------------------------------------------------------------------ cases (unsealed sets only)
def _doc(d: dict) -> dict:
    return {"key": d["key"], "title": d.get("title"), "type": d.get("doc_type"), "amends": d.get("amends"), "text": d["text"]}


def case_record(set_name: str, c: dict) -> dict:
    s = c["suite"]
    rec = {
        "id": c["id"],
        "set": set_name,
        "suite": s,
        "desc": c.get("description", ""),
        "docs": [_doc(d) for d in c["documents"]],
    }
    if s == "extraction":
        rec["gold"] = {
            "commitments": [
                {"q": g["quote_contains"], "type": g["type"], "party": g["obliging_party"], "modality": g["modality"]}
                for g in c["gold_commitments"]
            ],
            "max_extra": c.get("max_extra", 0),
        }
    elif s in ("deadline", "ambiguous"):
        rec["gold"] = c["gold"]
    elif s == "qa":
        rec["question"] = c["question"]
        rec["gold"] = {"status": c["gold_status"], "citations": c.get("gold_citation_contains", [])}
    else:
        rec["base"], rec["other"] = c["base_key"], c["other_key"]
        rec["gold"] = {
            "checks": [{"q": ch["subject_quote_contains"], "verdict": ch["gold_verdict"]} for ch in c["checks"]],
            "effects": [{"section": e["section"], "effect": e["effect"]} for e in c.get("gold_effects", [])],
        }
    return rec


def _v(x: str | None) -> str:
    if not x or x == "missing":
        return "nothing (no finding for that clause)"
    return x.replace("_", " ")


def judge(r: dict, system: str) -> tuple[bool, list[str], object]:
    """(passed, reasons it failed, compact output) for one case result."""
    s = r["suite"]
    if "error" in r:
        return False, [f"The run raised an error: {r['error']}"], None
    if s == "extraction":
        why = []
        if r["fn"]:
            why.append(f"Missed {r['fn']} of {r['tp'] + r['fn']} labelled commitments.")
        if r["fp"]:
            why.append(f"{r['fp']} extra commitment{'s' if r['fp'] != 1 else ''} beyond the tolerated extras.")
        if r["party_correct"] < r["party_total"]:
            why.append(f"Wrong obliging party on {r['party_total'] - r['party_correct']} matched commitment(s).")
        if r["type_correct"] < r["tp"]:
            why.append(f"Wrong commitment type on {r['tp'] - r['type_correct']} matched commitment(s).")
        out = [
            {
                "q": p["quote"],
                "party": p["obliging_party"],
                "type": p["type"],
                "modality": p["modality"],
                "conf": p["confidence"],
                "review": p["needs_review"],
                "deadline": (p.get("deadline") or {}).get("raw"),
            }
            for p in r["prediction"]
        ]
        return not why, why, {"found": r["tp"], "missed": r["fn"], "extra": r["fp"], "items": out}
    if s == "deadline":
        why = []
        if not r["found"]:
            why.append("It did not extract the commitment that carries the deadline.")
        else:
            if not r["kind_correct"]:
                why.append(f"Deadline kind is wrong: it said {_v(r['prediction'].get('kind'))}.")
            elif not r["correct"]:
                why.append("Deadline kind is right but the date, period or anchor is not.")
            if not r["cond_correct"]:
                why.append("Condition detection disagrees with the label.")
            if not r["exc_correct"]:
                why.append("Exception detection disagrees with the label.")
        return not why, why, r["prediction"]
    if s == "ambiguous":
        why = []
        if not r["found"]:
            why.append("It did not extract the vague commitment at all.")
        elif not r["correct"]:
            p = r["prediction"]
            why.append(
                "It did not flag the clause for review."
                if not p["needs_review"]
                else f"Flagged, but with {p['confidence']} confidence, above the label's ceiling."
            )
        return not why, why, r["prediction"]
    if s == "qa":
        why = []
        if r["pred"] != r["gold"]:
            why.append(f"The right answer is {_v(r['gold'])}, it said {_v(r['pred'])}.")
        if r["unsupported"]:
            why.append(f"{r['unsupported']} citation(s) failed verbatim verification.")
        if r["asserted_when_not_found"]:
            why.append("It answered a question the documents do not answer.")
        out = {"status": r["pred"], "conf": r.get("confidence"), "cit_recall": r.get("cit_recall")}
        if r.get("prediction"):
            out.update(answer=r["prediction"]["answer"], citations=r["prediction"]["citations"])
        elif system == "keyword":
            out["answer"] = "The keyword floor answers every question as stated, with no citations."
        return not why, why, out
    # verification suites
    why = []
    for i, ch in enumerate(r["checks"], 1):
        if ch["pred"] != ch["gold"]:
            why.append(f"Check {i}: the right answer is {_v(ch['gold'])}, it said {_v(ch['pred'])}.")
    for e in r.get("effects", []):
        if e["pred"] != e["gold"]:
            why.append(f"Section {e['section']}: the right answer is {_v(e['gold'])}, it said {_v(e['pred'])}.")
    out = {
        "checks": [{"verdict": ch["pred"], "why": ch.get("explanation")} for ch in r["checks"]],
        "effects": [e["pred"] for e in r.get("effects", [])],
    }
    if system == "keyword":
        out["note"] = "The keyword floor answers every check as consistent."
    return not why, why, out


# ------------------------------------------------------------------ static HTML (no-JS view)
def _2dp(v: float) -> str:
    # Half-up on the stored 3-dp value, matching docs/evaluation.md (0.695 -> 0.70, not float's 0.69).
    from decimal import ROUND_HALF_UP, Decimal

    return str(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def fmt(v: float | None) -> str:
    return "n/a" if v is None else _2dp(v)


def fmt_ci(p: dict | None) -> str:
    if not p or p.get("v") is None or not p.get("ci"):
        return ""
    return f"[{_2dp(p['ci'][0])}, {_2dp(p['ci'][1])}]"


def fmt_range(p: dict | None) -> str:
    """An interval for running prose: "0.51 to 0.69"."""
    return fmt_ci(p).strip("[]").replace(", ", " to ")


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def pct(v: float) -> str:
    return f"{max(0.0, min(1.0, v)) * 100:.1f}%"


def plot_row(run: dict, p: dict | None) -> str:
    cls = (
        "ev-row"
        + (" ev-row--floor" if run["system"] == "keyword" else "")
        + (" ev-row--old" if run["version"].startswith("v0.1") else "")
    )
    short = ("Rules " if run["system"] == "rules" else "Floor ") + run["version_label"]
    label = f'<span class="ev-row__label">{esc(short)}</span>'
    if not p or p.get("v") is None:
        note = (p or {}).get("note", "not measured")
        return (
            f'<div class="{cls}" role="listitem">{label}<span class="ev-row__plot" aria-hidden="true"></span>'
            f'<span class="ev-row__value"><span class="ev-row__n">{esc(note)}</span></span></div>'
        )
    lo, hi = p["ci"]
    method = "bootstrap" if p["m"] == "bootstrap" else "Wilson"
    title = f"{run['label']}: {fmt(p['v'])}, 95% {method} interval {fmt_ci(p)}, n={p['n']}"
    mark = (
        '<rect class="ev-mark ev-mark--floor" x="{x}" y="4" width="8" height="8" transform="translate(-4 0)"/>'
        if run["system"] == "keyword"
        else '<circle class="ev-mark" cx="{x}" cy="8" r="4.5"/>'
    )
    svg = (
        f'<svg class="ev-row__plot" width="100%" height="16" role="img"><title>{esc(title)}</title>'
        + f'<line class="ev-whisker" x1="{pct(lo)}" x2="{pct(hi)}" y1="8" y2="8"/>'
        + f'<line class="ev-whisker" x1="{pct(lo)}" x2="{pct(lo)}" y1="4" y2="12"/>'
        + f'<line class="ev-whisker" x1="{pct(hi)}" x2="{pct(hi)}" y1="4" y2="12"/>'
        + mark.format(x=pct(p["v"]))
        + "</svg>"
    )
    return (
        f'<div class="{cls}" role="listitem">{label}{svg}<span class="ev-row__value num">{fmt(p["v"])} '
        f'<span class="ev-row__n">{fmt_ci(p)} n={p["n"]}</span></span></div>'
    )


def axis_row() -> str:
    ticks = "".join(
        f'<text x="{t}%" y="11" text-anchor="{a}">{lbl}</text>'
        for t, a, lbl in ((0, "start", "0"), (50, "middle", "0.5"), (100, "end", "1"))
    )
    return (
        f'<div class="ev-row ev-row--axis" aria-hidden="true"><span class="ev-row__label"></span>'
        f'<svg class="ev-row__plot ev-axis" width="100%" height="14">{ticks}</svg>'
        f'<span class="ev-row__value"></span></div>'
    )


def render_chart(runs: list[dict]) -> str:
    parts = []
    for ds in SET_ORDER:
        rs = [r for r in runs if r["set"] == ds]
        panels = []
        for key, label, _plain, lower in METRICS:
            if not any(key in r["metrics"] for r in rs):
                continue
            # the post-fix re-runs scored identically (docs/evaluation.md); they stay in the table, not the chart
            rows = "".join(plot_row(r, r["metrics"].get(key)) for r in rs if r["version"] != "v0.2-postfix")
            better = ' <span class="ev-panel__better">(lower is better)</span>' if lower else ""
            panels.append(
                f'<figure class="ev-panel" data-metric="{key}"><figcaption><span class="ev-panel__title">'
                f'{esc(label)}</span>{better}</figcaption>'
                f'<div role="list">{rows}</div>{axis_row()}</figure>'
            )
        parts.append(
            f'<section class="ev-set" data-set="{ds}" aria-labelledby="chart-{ds}">'
            f'<h3 id="chart-{ds}" class="ev-set__title">{esc(SETS[ds]["long"])}</h3>'
            f'<p class="ev-set__about">{esc(SETS[ds]["about"])}</p>'
            f'<div class="ev-panels">{"".join(panels)}</div></section>'
        )
    return "\n".join(parts)


def render_tables(runs: list[dict]) -> str:
    parts = []
    for ds in SET_ORDER:
        rs = [r for r in runs if r["set"] == ds]
        head = "".join(f'<th scope="col">{esc(r["label"])}</th>' for r in rs)
        body = []
        for key, label, plain, lower in METRICS:
            if not any(key in r["metrics"] for r in rs):
                continue
            cells = []
            for r in rs:
                p = r["metrics"].get(key)
                if not p or p.get("v") is None:
                    cells.append('<td class="num">n/a</td>')
                    continue
                mark = "" if p["m"] == "bootstrap" else " W"
                cells.append(f'<td class="num">{fmt(p["v"])} <span class="ev-ci">{fmt_ci(p)}{mark} n={p["n"]}</span></td>')
            arrow = " (lower is better)" if lower else ""
            body.append(
                f'<tr><th scope="row">{esc(label)}{arrow}<span class="ev-plain">{esc(plain)}</span></th>'
                f'{"".join(cells)}</tr>'
            )
        parts.append(
            f'<div class="ev-table" data-set="{ds}" role="region" tabindex="0" '
            f'aria-labelledby="table-{ds}"><table><caption id="table-{ds}">{esc(SETS[ds]["long"])}: '
            f'value, 95% interval, n</caption><thead><tr><th scope="col">Metric</th>{head}</tr></thead>'
            f"<tbody>{''.join(body)}</tbody></table></div>"
        )
    return "\n".join(parts)


def render_provenance(runs: list[dict]) -> str:
    rows = []
    for r in runs:
        m = r["manifest"]
        commit = m["git_commit"] or ""
        ok = "yes" if r["dataset_hash_matches"] else "no"
        rows.append(
            f'<tr><th scope="row"><a href="{REPO}/tree/main/evals/runs/published/{r["id"]}">'
            f"<code>{esc(r['id'])}</code></a></th><td>{esc(SETS[r['set']]['label'])}</td>"
            f"<td>{esc(r['label'])}</td><td><code>{esc(commit[:12])}</code></td>"
            f'<td><code class="ev-hash">{esc(m["dataset_sha256"])}</code></td><td>{ok}</td></tr>'
        )
    return (
        '<div class="ev-table" role="region" tabindex="0" aria-labelledby="prov-cap"><table>'
        '<caption id="prov-cap">Every published run, the commit it was scored at and the SHA-256 of its dataset'
        '</caption><thead><tr><th scope="col">Run</th><th scope="col">Set</th><th scope="col">System</th>'
        '<th scope="col">Commit</th><th scope="col">Dataset SHA-256</th>'
        '<th scope="col">Hash matches the files today</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"
    )


def _get(runs: list[dict], run_id: str, key: str) -> dict:
    r = next(r for r in runs if r["id"] == run_id)
    return r["metrics"][key]


def render_headlines(runs: list[dict]) -> str:
    hal = _get(runs, "v2-holdout-rules", "hallucination_rate")
    hal_kw = _get(runs, "v2-holdout-keyword", "hallucination_rate")
    hal_x = round(hal["v"] * hal["n"])
    hal_w = wilson(hal_x, hal["n"])
    fc = _get(runs, "v2-holdout-rules", "false_clear_rate")
    fc_kw = _get(runs, "v2-holdout-keyword", "false_clear_rate")
    am2 = _get(runs, "v2-amendments-v2-rules", "verification_accuracy_amendment")
    am1 = _get(runs, "v1-amendments-v2-rules", "verification_accuracy_amendment")
    amk = _get(runs, "v2-amendments-v2-keyword", "verification_accuracy_amendment")
    ef2 = _get(runs, "v2-amendments-v2-rules", "amendment_effect_accuracy")
    ef1 = _get(runs, "v1-amendments-v2-rules", "amendment_effect_accuracy")
    wrong = round((1 - am2["v"]) * 10)
    con = _get(runs, "v2-holdout-rules", "verification_accuracy_consistency")
    conk = _get(runs, "v2-holdout-keyword", "verification_accuracy_consistency")
    am_runs = {r["id"]: r for r in runs}
    progress = "".join(
        plot_row(am_runs[i], am_runs[i]["metrics"]["verification_accuracy_amendment"])
        for i in ("v1-amendments-v2-rules", "v2-amendments-v2-rules", "v2-amendments-v2-keyword")
    )
    return f"""<li class="ev-answer ev-answer--lead">
  <h3>How good is it at amendments?</h3>
  <p class="ev-answer__figure num">{fmt(am2["v"])}</p>
  <p class="ev-answer__say">Wrong {wrong} in 10, on {am2["n"]} unseen checks. Mostly “needs review” where
    a change was real.</p>
  <div class="ev-progress" role="list" aria-label="Amendment verdict accuracy on the amendments set, by version">
    {progress}{axis_row()}
  </div>
  <p class="ev-answer__more">v0.1 {fmt(am1["v"])}, v0.2 {fmt(am2["v"])}, keyword floor {fmt(amk["v"])}.
    Effects: {fmt(ef1["v"])} then {fmt(ef2["v"])}.
    <a href="#cases" data-preset="amendments-v2:amendment:fail">Failed amendment cases</a></p>
</li>
<li class="ev-answer">
  <h3>How often does it make things up?</h3>
  <p class="ev-answer__figure num">{fmt(hal["v"])}</p>
  <p class="ev-answer__say">{hal_x} of {hal["n"]} sealed questions. Keyword floor: {fmt(hal_kw["v"])}.
    95% upper bound: {fmt(hal_w[1])}.</p>
</li>
<li class="ev-answer">
  <h3>How often does it wrongly say everything is fine?</h3>
  <p class="ev-answer__figure num">{fmt(fc["v"])}</p>
  <p class="ev-answer__say">{fc["x"]} of {fc["n"]} sealed checks. Keyword floor: {fmt(fc_kw["v"])}.</p>
</li>
<li class="ev-answer">
  <h3>Where is it no better than a simple baseline?</h3>
  <p class="ev-answer__figure num">{fmt(con["v"])} <span class="ev-answer__vs">vs {fmt(conk["v"])}</span></p>
  <p class="ev-answer__say">Consistency suite, against always saying “consistent”. The intervals
    overlap: {fmt_range(con)} and {fmt_range(conk)}.</p>
</li>"""


def splice(page: str, name: str, content: str) -> str:
    pat = re.compile(rf"(<!-- build:{name} -->)(.*?)(<!-- /build:{name} -->)", re.S)
    if not pat.search(page):
        raise SystemExit(f"{PAGE} has no <!-- build:{name} --> region")
    return pat.sub(lambda m: f"{m.group(1)}\n{content}\n{m.group(3)}", page, count=1)


# ------------------------------------------------------------------ build
def dumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def build() -> dict[Path, str]:
    runs = load_runs()
    files: dict[Path, str] = {}

    public_runs = [{k: v for k, v in r.items() if not k.startswith("_")} for r in runs]
    files[OUT / "summary.json"] = dumps(
        {
            "about": "Aggregates for every published run (evals/runs/published). Intervals: 'bootstrap' is the runner's "
            "95% bootstrap CI over cases (1,000 resamples, seed 7); 'wilson' is a 95% Wilson score interval "
            "computed by scripts/build_site_data.py from the published value and n. Holdout runs are sealed: "
            "aggregates only.",
            "metrics": [{"key": k, "label": lbl, "plain": pl, "lower_is_better": lo} for k, lbl, pl, lo in METRICS],
            "runs": public_runs,
            "sets": {k: {**v, "sealed": k in SEALED} for k, v in SETS.items()},
        }
    )

    cases: list[dict] = []
    for ds in SET_ORDER:
        if ds in SEALED:
            continue  # sealed: never read its cases
        for s in SUITES:
            f = DATASETS / ds / f"{s}.jsonl"
            if f.exists():
                cases += [case_record(ds, c) for c in _read_jsonl(f)]
    known = {c["id"] for c in cases}
    results: dict[str, dict] = {}
    for r in runs:
        if r["sealed"]:
            continue  # sealed: never read its cases.jsonl
        per: dict[str, dict] = {}
        for row in _read_jsonl(r["_dir"] / "cases.jsonl"):
            if row.get("repeat", 0) != 0:
                continue
            if row["case_id"] not in known:
                raise SystemExit(f"{r['id']}: case {row['case_id']} is not in evals/datasets/{r['set']}")
            ok, why, out = judge(row, r["system"])
            per[row["case_id"]] = {"pass": ok, "why": why, "out": out}
        results[r["id"]] = per
    files[OUT / "cases.json"] = dumps(
        {
            "about": "Every case of the unsealed sets (core, amendments-v2) with its documents and gold labels, and each "
            "run's output on it. A case passes when every check in it is right. Holdout cases are sealed and "
            "absent.",
            "cases": cases,
            "results": results,
            "runs": [
                {"id": r["id"], "set": r["set"], "system": r["system"], "version": r["version"], "label": r["label"]}
                for r in runs
                if not r["sealed"]
            ],
            "suites": SUITE_LABELS,
        }
    )

    page = PAGE.read_text(encoding="utf-8")
    page = splice(page, "headlines", render_headlines(runs))
    page = splice(page, "chart", render_chart(runs))
    page = splice(page, "tables", render_tables(runs))
    page = splice(page, "provenance", render_provenance(runs))
    files[PAGE] = page
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the files on disk differ from a fresh build")
    args = ap.parse_args()
    files = build()
    stale = [p for p, text in files.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
    if args.check:
        for p in stale:
            print(f"stale: {p.relative_to(ROOT)}", file=sys.stderr)
        if stale:
            print("Run: python scripts/build_site_data.py", file=sys.stderr)
        return 1 if stale else 0
    for p, text in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        print(f"wrote {p.relative_to(ROOT)} ({len(text.encode('utf-8')):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
