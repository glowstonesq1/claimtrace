"""Analysis time must grow roughly linearly with document size.

v0.3 took ~98 s on a repetitive 108 KB .txt and never finished on 7.9 MB: sentence splitting did not break
"... days. 1.1 The Vendor ...", so the whole file became one sentence, and every commitment re-scanned it.
These budgets are loose for slow CI runners but fail by a wide margin on a quadratic regression.
"""

from __future__ import annotations

import time

import pytest

from claimtrace.browser import Session

SHAPES = {
    # numbered clauses run together on one line (the review's reproduction)
    "numbered": b"1.1 The Vendor shall deliver the item within 30 days. ",
    # one endless sentence: no full stop followed by a capital, so nothing to split on
    "run-on": b"the Vendor shall deliver the item within 30 days; ",
}


def _seconds(unit: bytes, n: int) -> tuple[float, dict]:
    s = Session()
    t = time.perf_counter()
    reg = s.analyze([{"name": "big.txt", "bytes": unit * n}])
    return time.perf_counter() - t, reg


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_analyze_time_is_linear(shape: str) -> None:
    unit = SHAPES[shape]
    small, _ = _seconds(unit, 500)
    big, reg = _seconds(unit, 2000)  # ~108 KB
    assert reg["commitments"], "the big file should still yield commitments"
    assert big < 5.0, f"{shape}: 2000 clauses took {big:.1f}s (budget 5s)"
    # linear growth is 4x; quadratic is 16x. Floor the small time so timer noise cannot fail it.
    assert big / max(small, 0.15) < 8, f"{shape}: 500 -> 2000 clauses went {small:.2f}s -> {big:.2f}s"


def test_quotes_stay_short_on_run_on_text() -> None:
    """A commitment quote is a sentence, not the whole file: output size must not grow with n squared."""
    _, reg = _seconds(SHAPES["run-on"], 2000)
    assert max(len(c["text"]) for c in reg["commitments"]) < 5000
