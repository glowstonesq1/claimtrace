"""Reproducible evaluation runner: `claimtrace eval run|report`.

Each run writes evals/runs/<timestamp>-<system>/ with:
  manifest.json  versions, dataset hash, git commit, timestamp, system
  cases.jsonl    per-case inputs ids, gold, prediction, correctness, latency (raw outputs)
  summary.json   metrics with bootstrap 95% confidence intervals
Metric definitions are in docs/evaluation.md and were fixed before tuning (design-review D22).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from claimtrace import __version__
from claimtrace.core.models import CONFIDENCE_ORDER, Commitment, Confidence
from claimtrace.core.store import Store
from claimtrace.core.text import NORMALIZER_VERSION, squash

SUITES = ["extraction", "deadline", "consistency", "contradiction", "qa", "evidence_gap", "amendment", "ambiguous"]
ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------ data
def load_suite_set(name: str) -> dict[str, list[dict]]:
    base = ROOT / "evals" / "datasets" / name
    if not base.exists():
        raise SystemExit(f"No dataset at {base}")
    out = {}
    for s in SUITES:
        f = base / f"{s}.jsonl"
        if f.exists():
            out[s] = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    return out


def dataset_hash(name: str) -> str:
    h = hashlib.sha256()
    for f in sorted((ROOT / "evals" / "datasets" / name).glob("*.jsonl")):
        h.update(f.read_bytes())
    return h.hexdigest()


def contains(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    x, y = squash(a), squash(b)
    return x in y or y in x


# ------------------------------------------------------------------ systems
class System:
    """Wraps the pipeline under test. `keyword` is the trivial floor; `rules` and LLM variants use ClaimTrace."""

    def __init__(self, spec: str) -> None:
        self.spec = spec
        self.provider = None
        self.chars_sent = 0
        if spec.startswith(("openai:", "ollama:")):
            import os

            from claimtrace.core.config import Settings
            from claimtrace.integrations.llm import provider_from_settings

            kind, model = spec.split(":", 1)
            s = Settings()
            s.llm_provider, s.llm_model = kind, model
            s.llm_base_url = s.llm_base_url or (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
                                                if kind == "openai" else None)
            self.provider = provider_from_settings(s)
        elif spec not in ("rules", "keyword"):
            raise SystemExit("--model must be rules, keyword, openai:<model> or ollama:<model>")

    def build(self, case: dict) -> tuple[Store, dict[str, str]]:
        from claimtrace.extraction import analyze_document, apply_amendments
        from claimtrace.ingestion import IngestOptions, ingest_bytes

        store = Store()
        ids: dict[str, str] = {}
        docs = sorted(case["documents"], key=lambda d: 1 if d.get("amends") else 0)
        for d in docs:
            opts = IngestOptions(title=d.get("title"), doc_type=d.get("doc_type"), sandbox=False,
                                 amends_document_id=ids.get(d["amends"]) if d.get("amends") else None,
                                 allow_external_llm=True)  # synthetic eval data only
            doc = ingest_bytes(store, f"{case['id']}-{d['key']}.md", d["text"].encode(), opts)
            ids[d["key"]] = doc.id
        apply_amendments(store)
        if self.spec != "keyword":
            for key in [d["key"] for d in docs]:
                analyze_document(store, ids[key], self.provider)
        return store, ids


def _keyword_commitments(text: str) -> list[dict]:
    """Trivial floor: every sentence with a modal verb is a commitment by the first capitalised word."""
    out = []
    for sent in re.split(r"(?<=[.;])\s+", text):
        m = re.search(r"\b(shall not|must not|shall|must|will|may)\b", sent)
        if m:
            subj = re.findall(r"\b(?:the\s+)?([A-Z][a-z]+)\b", sent[: m.start()])
            out.append({"quote": sent.strip(), "obliging_party": subj[-1] if subj else None,
                        "modality": {"shall not": "must_not", "must not": "must_not", "may": "may"}.get(m.group(1), "must"),
                        "type": "prohibition" if "not" in m.group(1) else "entitlement" if m.group(1) == "may" else
                        "obligation", "confidence": "medium", "needs_review": False, "deadline": None,
                        "conditions": [], "exceptions": []})
    return out


def _system_commitments(system: System, store: Store, ids: dict[str, str], case: dict) -> list[dict]:
    if system.spec == "keyword":
        return [c for d in case["documents"] for c in _keyword_commitments(d["text"])]
    out = []
    for doc_id in ids.values():
        for c in store.objects(Commitment, doc_id):
            out.append({"quote": c.text, "obliging_party": c.obliging_party, "modality": c.modality.value,
                        "type": c.type.value, "confidence": c.confidence.value, "needs_review": c.needs_review,
                        "deadline": c.deadline.model_dump(mode="json") if c.deadline else None,
                        "conditions": c.conditions, "exceptions": c.exceptions, "section": c.section_number,
                        "document_effect": c.document_effect.value})
    return out


# ------------------------------------------------------------------ scorers (one per suite)
def score_extraction(system: System, case: dict) -> dict:
    store, ids = system.build(case)
    preds = _system_commitments(system, store, ids, case)
    gold = case["gold_commitments"]
    used: set[int] = set()
    matches = []
    for g in gold:
        cands = [i for i, p in enumerate(preds) if i not in used and contains(g["quote_contains"], p["quote"])]
        if not cands:
            matches.append((g, None))
            continue
        best = max(cands, key=lambda i: (preds[i]["modality"] == g["modality"], preds[i]["type"] == g["type"]))
        used.add(best)
        matches.append((g, preds[best]))
    tp = sum(1 for _, p in matches if p)
    fp_raw = len(preds) - len(used)
    fp = max(0, fp_raw - int(case.get("max_extra", 0)))
    party_ok = [(_party(g["obliging_party"]) == _party(p["obliging_party"])) for g, p in matches if p]
    calib = [(p["confidence"], True) for _, p in matches if p] + \
            [(p["confidence"], False) for i, p in enumerate(preds) if i not in used][: max(fp, 0)]
    return {"tp": tp, "fn": len(gold) - tp, "fp": fp, "party_correct": sum(party_ok), "party_total": len(party_ok),
            "type_correct": sum(1 for g, p in matches if p and p["type"] == g["type"]),
            "modality_correct": sum(1 for g, p in matches if p and p["modality"] == g["modality"]),
            "flagged": sum(1 for p in preds if p["needs_review"]), "n_pred": len(preds), "calibration": calib,
            "prediction": preds}


def _party(p: str | None) -> str | None:
    if not p:
        return None
    return re.sub(r"^(?:the)\s+", "", p.strip().lower())


def score_deadline(system: System, case: dict) -> dict:
    store, ids = system.build(case)
    g = case["gold"]
    preds = _system_commitments(system, store, ids, case)
    p = next((x for x in preds if contains(g["quote_contains"], x["quote"])), None)
    if p is None:
        return {"found": False, "correct": False, "kind_correct": False, "cond_correct": False, "exc_correct": False,
                "prediction": None}
    dl = p["deadline"] or {"kind": "none"}
    kind_ok = dl.get("kind") == g["deadline_kind"]
    detail_ok = kind_ok
    if kind_ok and g["deadline_kind"] == "absolute" and g.get("date"):
        detail_ok = dl.get("date") == g["date"]
    if kind_ok and g["deadline_kind"] == "relative":
        if g.get("offset_days") is not None:
            detail_ok = dl.get("offset_days") == g["offset_days"]
        if g.get("business_days") is not None:
            detail_ok = detail_ok and bool(dl.get("business_days")) == bool(g["business_days"])
        if g.get("anchor_contains"):
            detail_ok = detail_ok and contains(g["anchor_contains"], dl.get("anchor") or dl.get("raw"))
    cond_ok = bool(p["conditions"]) == bool(g.get("has_condition"))
    exc_ok = bool(p["exceptions"]) == bool(g.get("has_exception"))
    return {"found": True, "correct": detail_ok, "kind_correct": kind_ok, "cond_correct": cond_ok,
            "exc_correct": exc_ok, "prediction": dl}


def score_verification(system: System, case: dict) -> dict:
    from claimtrace.core.models import Commitment as C
    from claimtrace.verification import verify_documents

    if system.spec == "keyword":
        results = [{"gold": ch["gold_verdict"], "pred": "consistent", "found": True} for ch in case["checks"]]
        return {"checks": results, "effects": [], "prediction": "keyword: always consistent"}
    store, ids = system.build(case)
    run = verify_documents(store, ids[case["base_key"]], ids[case["other_key"]])
    results = []
    for ch in case["checks"]:
        f = next((f for f in run.findings if contains(ch["subject_quote_contains"], f.subject_text)), None)
        results.append({"gold": ch["gold_verdict"], "pred": f.verdict.value if f else "missing", "found": f is not None,
                        "explanation": f.explanation if f else None})
    effects = []
    for ge in case.get("gold_effects", []):
        cs = [c for c in store.objects(C, ids[case["base_key"]]) if c.section_number == ge["section"]]
        pred = cs[0].document_effect.value if cs else "missing"
        effects.append({"section": ge["section"], "gold": ge["effect"], "pred": pred})
    return {"checks": results, "effects": effects, "mode": run.mode,
            "prediction": [{"subject": f.subject_text[:120], "verdict": f.verdict.value} for f in run.findings]}


def score_qa(system: System, case: dict) -> dict:
    from claimtrace.verification import answer_question

    gold_status = case["gold_status"]
    if system.spec == "keyword":
        return {"gold": gold_status, "pred": "stated", "cit_recall": 0.0, "cit_precision": 0.0, "unsupported": 0,
                "asserted_when_not_found": gold_status == "not_addressed", "confidence": "medium", "prediction": None}
    store, ids = system.build(case)
    ans = answer_question(store, case["question"], list(ids.values()), provider=system.provider,
                          today=dt.date(2026, 1, 1))
    cits = [c for c in ans.citations if c.role in ("supports", "conflicts", "context")]
    gold_c = case.get("gold_citation_contains", [])
    hit = [g for g in gold_c if any(contains(g, c.span.quote) for c in cits)]
    prec_hits = [c for c in cits if any(contains(g, c.span.quote) for g in gold_c)] if gold_c else []
    return {"gold": gold_status, "pred": ans.status.value,
            "cit_recall": len(hit) / len(gold_c) if gold_c else None,
            "cit_precision": (len(prec_hits) / len(cits) if cits else 0.0) if gold_c else None,
            "unsupported": sum(1 for c in ans.citations if not c.verified),
            "asserted_when_not_found": gold_status == "not_addressed" and ans.status.value != "not_addressed",
            "confidence": ans.confidence.value,
            "prediction": {"status": ans.status.value, "answer": ans.answer_text[:600],
                           "citations": [c.span.quote for c in ans.citations]}}


def score_ambiguous(system: System, case: dict) -> dict:
    store, ids = system.build(case)
    g = case["gold"]
    preds = _system_commitments(system, store, ids, case)
    p = next((x for x in preds if contains(g["quote_contains"], x["quote"])), None)
    if p is None:
        return {"found": False, "correct": False, "prediction": None}
    ok = bool(p["needs_review"]) and CONFIDENCE_ORDER[Confidence(p["confidence"])] <= \
        CONFIDENCE_ORDER[Confidence(g["max_confidence"])]
    return {"found": True, "correct": ok, "prediction": {"needs_review": p["needs_review"],
                                                          "confidence": p["confidence"]}}


SCORERS: dict[str, Callable[[System, dict], dict]] = {
    "extraction": score_extraction, "deadline": score_deadline, "consistency": score_verification,
    "contradiction": score_verification, "evidence_gap": score_verification, "amendment": score_verification,
    "qa": score_qa, "ambiguous": score_ambiguous,
}


# ------------------------------------------------------------------ aggregation
def bootstrap_ci(values: list[float], n: int = 1000, seed: int = 7) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(n))
    return (round(means[int(0.025 * n)], 3), round(means[int(0.975 * n) - 1], 3))


def _metric(values: list[float]) -> dict:
    if not values:
        return {"value": None, "n": 0}
    return {"value": round(sum(values) / len(values), 3), "ci95": bootstrap_ci(values), "n": len(values)}


def summarise(results: dict[str, list[dict]]) -> dict:
    m: dict[str, dict] = {}
    ex = [r for r in results.get("extraction", []) if "error" not in r]
    if ex:
        tp, fp, fn = (sum(r[k] for r in ex) for k in ("tp", "fp", "fn"))
        per_case_p = [r["tp"] / (r["tp"] + r["fp"]) for r in ex if r["tp"] + r["fp"]]
        per_case_r = [r["tp"] / (r["tp"] + r["fn"]) for r in ex if r["tp"] + r["fn"]]
        m["commitment_precision"] = {**_metric(per_case_p), "micro": round(tp / (tp + fp), 3) if tp + fp else None}
        m["commitment_recall"] = {**_metric(per_case_r), "micro": round(tp / (tp + fn), 3) if tp + fn else None}
        pt = sum(r["party_total"] for r in ex)
        m["party_attribution_accuracy"] = {"value": round(sum(r["party_correct"] for r in ex) / pt, 3) if pt else None,
                                           "n": pt}
        m["commitment_type_accuracy"] = {"value": round(sum(r["type_correct"] for r in ex) / tp, 3) if tp else None,
                                         "n": tp}
        npred = sum(r["n_pred"] for r in ex)
        m["review_burden"] = {"value": round(sum(r["flagged"] for r in ex) / npred, 3) if npred else None, "n": npred,
                              "note": "share of extracted commitments flagged for human review"}
        buckets: dict[str, list[float]] = {}
        for r in ex:
            for conf, ok in r["calibration"]:
                buckets.setdefault(conf, []).append(1.0 if ok else 0.0)
        m["calibration_extraction"] = {k: _metric(v) for k, v in sorted(buckets.items())}
    dl = [r for r in results.get("deadline", []) if "error" not in r]
    if dl:
        m["deadline_accuracy"] = _metric([1.0 if r["correct"] else 0.0 for r in dl])
        m["deadline_kind_accuracy"] = _metric([1.0 if r["kind_correct"] else 0.0 for r in dl])
        m["condition_detection_accuracy"] = _metric([1.0 if r["cond_correct"] else 0.0 for r in dl if r["found"]])
        m["exception_detection_accuracy"] = _metric([1.0 if r["exc_correct"] else 0.0 for r in dl if r["found"]])
    all_checks = []
    for s in ("consistency", "contradiction", "evidence_gap", "amendment"):
        rs = [r for r in results.get(s, []) if "error" not in r]
        checks = [c for r in rs for c in r["checks"]]
        all_checks += checks
        if checks:
            m[f"verification_accuracy_{s}"] = _metric([1.0 if c["pred"] == c["gold"] else 0.0 for c in checks])
        if s == "amendment":
            eff = [e for r in rs for e in r["effects"]]
            if eff:
                m["amendment_effect_accuracy"] = _metric([1.0 if e["pred"] == e["gold"] else 0.0 for e in eff])
    if all_checks:
        m["verification_accuracy_all"] = _metric([1.0 if c["pred"] == c["gold"] else 0.0 for c in all_checks])
        tp = sum(1 for c in all_checks if c["gold"] == "contradicted" and c["pred"] == "contradicted")
        fp = sum(1 for c in all_checks if c["gold"] != "contradicted" and c["pred"] == "contradicted")
        fn = sum(1 for c in all_checks if c["gold"] == "contradicted" and c["pred"] != "contradicted")
        m["contradiction_detection"] = {"precision": round(tp / (tp + fp), 3) if tp + fp else None,
                                        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
                                        "n_gold_contradictions": tp + fn}
        fc = sum(1 for c in all_checks if c["pred"] == "consistent" and c["gold"] in ("contradicted",
                                                                                      "partially_supported"))
        m["false_clear_rate"] = {"value": round(fc / len(all_checks), 3), "n": len(all_checks),
                                 "note": "predicted consistent when gold was contradicted/partially_supported"}
    qa = [r for r in results.get("qa", []) if "error" not in r]
    if qa:
        m["qa_status_accuracy"] = _metric([1.0 if r["pred"] == r["gold"] else 0.0 for r in qa])
        cr = [r["cit_recall"] for r in qa if r["cit_recall"] is not None]
        cp = [r["cit_precision"] for r in qa if r["cit_precision"] is not None]
        m["citation_recall"] = _metric(cr)
        m["citation_precision"] = _metric(cp)
        nf_gold = [r for r in qa if r["gold"] == "not_addressed"]
        nf_pred = [r for r in qa if r["pred"] == "not_addressed"]
        m["not_found_recall"] = _metric([1.0 if r["pred"] == "not_addressed" else 0.0 for r in nf_gold])
        m["not_found_precision"] = _metric([1.0 if r["gold"] == "not_addressed" else 0.0 for r in nf_pred])
        m["hallucination_rate"] = _metric([1.0 if (r["unsupported"] > 0 or r["asserted_when_not_found"]) else 0.0
                                           for r in qa])
        qb: dict[str, list[float]] = {}
        for r in qa:
            qb.setdefault(r["confidence"], []).append(1.0 if r["pred"] == r["gold"] else 0.0)
        m["calibration_qa"] = {k: _metric(v) for k, v in sorted(qb.items())}
    am = [r for r in results.get("ambiguous", []) if "error" not in r]
    if am:
        m["ambiguity_flag_accuracy"] = _metric([1.0 if r["correct"] else 0.0 for r in am])
    lat = [r["latency_ms"] for rs in results.values() for r in rs if "latency_ms" in r]
    if lat:
        lat.sort()
        m["latency_ms"] = {"p50": lat[len(lat) // 2], "p95": lat[int(len(lat) * 0.95) - 1], "n": len(lat)}
    m["errors"] = {s: sum(1 for r in rs if "error" in r) for s, rs in results.items()}
    m["cases"] = {s: len(rs) for s, rs in results.items()}
    return m


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def run_cmd(suite: str, model: str, out: str, repeats: int = 1) -> int:
    from claimtrace.extraction.llm import PROMPT_VERSION
    from claimtrace.extraction.rules import EXTRACTOR_VERSION
    from claimtrace.verification.ask import ANSWER_PROMPT_VERSION

    data = load_suite_set(suite)
    system = System(model)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / out / f"{stamp}-{model.replace(':', '_').replace('/', '_')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, list[dict]] = {}
    with (run_dir / "cases.jsonl").open("w") as fh:
        for s, cases in data.items():
            results[s] = []
            for case in cases:
                for rep in range(repeats):
                    t0 = time.monotonic()
                    try:
                        r = SCORERS[s](system, case)
                    except Exception as e:  # noqa: BLE001 - record failures, never hide them
                        r = {"error": f"{type(e).__name__}: {e}"[:300]}
                    r["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
                    r["case_id"], r["suite"], r["repeat"] = case["id"], s, rep
                    results[s].append(r)
                    fh.write(json.dumps(r, default=str) + "\n")
    manifest = {"claimtrace_version": __version__, "system": model, "suite": suite,
                "dataset_sha256": dataset_hash(suite), "git_commit": _git_commit(), "timestamp": stamp,
                "extractor_version": EXTRACTOR_VERSION, "normalizer_version": NORMALIZER_VERSION,
                "extract_prompt_version": PROMPT_VERSION if system.provider else None,
                "answer_prompt_version": ANSWER_PROMPT_VERSION if system.provider else None,
                "model": getattr(system.provider, "model", None), "repeats": repeats,
                "python": sys.version.split()[0]}
    summary = summarise(results)
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"Wrote {run_dir.relative_to(ROOT)}")
    print(render_markdown(manifest, summary))
    return 0


def _fmt(v: dict | None) -> str:
    if not v or v.get("value") is None:
        return "–"
    ci = v.get("ci95")
    ci_s = f" [{ci[0]:.2f}–{ci[1]:.2f}]" if ci and ci[0] == ci[0] else ""
    return f"{v['value']:.2f}{ci_s} (n={v['n']})"


def render_markdown(manifest: dict, s: dict) -> str:
    rows = [
        ("Commitment precision (per-case mean)", _fmt(s.get("commitment_precision")),
         f"micro {s.get('commitment_precision', {}).get('micro')}"),
        ("Commitment recall (per-case mean)", _fmt(s.get("commitment_recall")),
         f"micro {s.get('commitment_recall', {}).get('micro')}"),
        ("Party attribution accuracy", _fmt(s.get("party_attribution_accuracy")), "on matched commitments"),
        ("Commitment type accuracy", _fmt(s.get("commitment_type_accuracy")), "on matched commitments"),
        ("Deadline accuracy (kind + value)", _fmt(s.get("deadline_accuracy")), ""),
        ("Deadline kind accuracy", _fmt(s.get("deadline_kind_accuracy")), ""),
        ("Condition detection", _fmt(s.get("condition_detection_accuracy")), ""),
        ("Exception detection", _fmt(s.get("exception_detection_accuracy")), ""),
        ("Verification accuracy — consistency", _fmt(s.get("verification_accuracy_consistency")), ""),
        ("Verification accuracy — contradiction", _fmt(s.get("verification_accuracy_contradiction")), ""),
        ("Verification accuracy — evidence gap", _fmt(s.get("verification_accuracy_evidence_gap")), ""),
        ("Verification accuracy — amendment", _fmt(s.get("verification_accuracy_amendment")), ""),
        ("Amendment effect accuracy", _fmt(s.get("amendment_effect_accuracy")), "replaced/deleted/in_force"),
        ("Contradiction detection P / R", f"{s.get('contradiction_detection', {}).get('precision')} / "
                                          f"{s.get('contradiction_detection', {}).get('recall')}",
         f"n={s.get('contradiction_detection', {}).get('n_gold_contradictions')}"),
        ("False-clear rate (said consistent, was not)", _fmt(s.get("false_clear_rate")), "lower is better"),
        ("Grounded QA status accuracy", _fmt(s.get("qa_status_accuracy")), ""),
        ("Citation recall", _fmt(s.get("citation_recall")), ""),
        ("Citation precision", _fmt(s.get("citation_precision")), ""),
        ("'Not found' recall", _fmt(s.get("not_found_recall")), ""),
        ("'Not found' precision", _fmt(s.get("not_found_precision")), ""),
        ("Hallucination rate", _fmt(s.get("hallucination_rate")), "unverified quote or answered a not-found case"),
        ("Ambiguity flagged correctly", _fmt(s.get("ambiguity_flag_accuracy")), ""),
        ("Review burden", _fmt(s.get("review_burden")), "share of commitments flagged"),
        ("Latency per case (ms) p50 / p95", f"{s.get('latency_ms', {}).get('p50')} / {s.get('latency_ms', {}).get('p95')}",
         ""),
    ]
    lines = [f"### Eval: system `{manifest['system']}` · suite `{manifest['suite']}` · {manifest['timestamp']}", "",
             f"ClaimTrace {manifest['claimtrace_version']} · extractor {manifest['extractor_version']} · dataset "
             f"`{manifest['dataset_sha256'][:12]}` · commit `{(manifest.get('git_commit') or 'n/a')[:10]}`", "",
             "| Metric | Value [95% CI] | Note |", "|---|---|---|"]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    cal = s.get("calibration_extraction") or {}
    if cal:
        lines += ["", "Calibration (extraction precision by confidence label): " +
                  ", ".join(f"{k}: {v['value']} (n={v['n']})" for k, v in cal.items())]
    calq = s.get("calibration_qa") or {}
    if calq:
        lines.append("Calibration (QA accuracy by confidence label): " +
                     ", ".join(f"{k}: {v['value']} (n={v['n']})" for k, v in calq.items()))
    lines.append(f"Cases: {s.get('cases')} · errors: {s.get('errors')}")
    return "\n".join(lines)


def report_cmd(run: str | None, fmt: str, out_dir: str) -> int:
    base = ROOT / out_dir
    if run:
        run_dir = Path(run) if Path(run).is_absolute() else ROOT / run
    else:
        runs = sorted(p for p in base.iterdir() if (p / "summary.json").exists())
        if not runs:
            print("No eval runs found. Run `claimtrace eval run` first.")
            return 1
        run_dir = runs[-1]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    summary = json.loads((run_dir / "summary.json").read_text())
    if fmt == "json":
        print(json.dumps({"manifest": manifest, "summary": summary}, indent=2))
    else:
        print(render_markdown(manifest, summary))
    return 0
