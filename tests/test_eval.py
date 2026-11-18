from claimtrace.evaluation.runner import SCORERS, System, load_suite_set, summarise


def test_eval_smoke_one_case_per_suite():
    data = load_suite_set("core")
    system = System("rules")
    results = {s: [SCORERS[s](system, cases[0])] for s, cases in data.items()}
    m = summarise(results)
    assert m["errors"] == {s: 0 for s in data}
    assert "commitment_recall" in m and "hallucination_rate" in m


def test_keyword_floor_runs():
    data = load_suite_set("core")
    r = SCORERS["extraction"](System("keyword"), data["extraction"][0])
    assert r["n_pred"] > 0
