"""Regex denial-of-service: every recogniser must stay (near) linear on long whitespace runs.

Uploaded documents are attacker-controlled, and `normalize()` used to keep exotic whitespace
(U+1680, \\v, \\f, U+0085, U+2028) that the extraction regexes treat as `\\s`. A single passage with a
20k-character run of it made `MODIFY_WORDS_IN_RE` / `MODIFY_IN_RE` backtrack quadratically or worse.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
import signal
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest

import claimtrace.extraction as extraction
from claimtrace.core.text import normalize
from claimtrace.extraction.amendments import parse_instructions

N = 20_000
BUDGET = 1.0  # seconds per call
WHITESPACE = [" ", " ", "\v", "\f", "\x85", " ", " ", "　", "\t"]


@contextmanager
def _deadline(seconds: float) -> Iterator[None]:
    """Abort a runaway regex instead of hanging the suite (the sre engine checks signals)."""

    def _raise(signum: int, frame: object) -> None:
        raise TimeoutError(f"exceeded {seconds}s")

    old = signal.signal(signal.SIGALRM, _raise)
    signal.setitimer(signal.ITIMER_REAL, seconds * 5)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def _timed(fn: Callable[[], object]) -> float:
    t = time.perf_counter()
    try:
        with _deadline(BUDGET):
            fn()
    except TimeoutError:
        return float("inf")
    return time.perf_counter() - t


@pytest.mark.parametrize("ws", WHITESPACE, ids=lambda w: f"U+{ord(w):04X}")
def test_modify_words_in_whitespace_run_is_fast(ws: str) -> None:
    raw = "In clause 1 the words x" + ws * N
    assert _timed(lambda: parse_instructions(normalize(raw))) < BUDGET
    assert _timed(lambda: parse_instructions(raw)) < BUDGET
    assert _timed(lambda: parse_instructions(raw + "y")) < BUDGET


@pytest.mark.parametrize("ws", WHITESPACE, ids=lambda w: f"U+{ord(w):04X}")
def test_normalize_collapses_all_unicode_whitespace(ws: str) -> None:
    out = normalize("a" + ws * 50 + "b")
    assert re.fullmatch(r"a(?: |\n\n)b", out), repr(out)
    # nothing but plain spaces and paragraph breaks survives normalisation
    assert not re.search(r"[^\S \n]", normalize(f"x{ws}y{ws}{ws}z"))


def _extraction_patterns() -> list[tuple[str, re.Pattern[str]]]:
    out = []
    for info in pkgutil.iter_modules(extraction.__path__):
        mod = importlib.import_module(f"{extraction.__name__}.{info.name}")
        for name, value in vars(mod).items():
            if isinstance(value, re.Pattern):
                out.append((f"{info.name}.{name}", value))
            elif isinstance(value, list):  # e.g. patterns.DATE_PATTERNS = [(re.Pattern, kind), ...]
                for i, item in enumerate(value):
                    rx = item[0] if isinstance(item, tuple) and item else item
                    if isinstance(rx, re.Pattern):
                        out.append((f"{info.name}.{name}[{i}]", rx))
    return out


PATTERNS = _extraction_patterns()
# Prefixes that walk each recogniser as far as possible into the whitespace run.
PREFIXES = [
    "",
    "x",
    "1",
    "clause 1",
    "clause 1 of the Agreement",
    "in clause 1,",
    "In clause 1 the words x",
    "the words x",
    "\"x\"",
    "Schedule 1",
    "after clause 1",
    "within 30",
    "30 days",
    "if x",
    "except x",
    "shall",
]


def test_pattern_inventory_is_not_empty() -> None:
    assert len(PATTERNS) > 30


@pytest.mark.parametrize("ws", [" ", " "], ids=["space", "ogham"])
@pytest.mark.parametrize("name,rx", PATTERNS, ids=[n for n, _ in PATTERNS])
def test_extraction_regex_linear_on_whitespace_runs(name: str, rx: re.Pattern[str], ws: str) -> None:
    slow = []
    for prefix in PREFIXES:
        for tail in ("", "y", "."):
            s = prefix + ws * N + tail
            dt = _timed(lambda s=s: [m.span() for m in rx.finditer(s)])  # type: ignore[misc]
            if dt >= BUDGET:
                slow.append((prefix, tail, dt))
    assert not slow, f"{name}: {slow}"
