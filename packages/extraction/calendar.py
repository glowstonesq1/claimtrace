"""Business-day arithmetic with a configurable holiday list.

Holidays come from the file named by `CLAIMTRACE_HOLIDAYS`: one ISO date (YYYY-MM-DD) per line;
blank lines and `#` comments are ignored. A malformed or missing file is an error, never a silent
fallback, because a wrong calendar produces wrong dates.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os

Holidays = frozenset[dt.date]


def load_holidays(path: str) -> Holidays:
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as e:
        raise ValueError(f"Holiday file '{path}' could not be read.") from e
    out: set[dt.date] = set()
    for n, line in enumerate(lines, start=1):
        value = line.split("#", 1)[0].strip()
        if not value:
            continue
        try:
            out.add(dt.date.fromisoformat(value))
        except ValueError as e:
            raise ValueError(f"Holiday file '{path}' line {n}: expected an ISO date (YYYY-MM-DD).") from e
    return frozenset(out)


def holidays_from_env() -> Holidays:
    path = os.environ.get("CLAIMTRACE_HOLIDAYS", "").strip()
    return load_holidays(path) if path else frozenset()


def calendar_id(holidays: Holidays) -> str | None:
    """Short fingerprint of a holiday set (part of the analysis idempotency key), or None if empty."""
    if not holidays:
        return None
    return hashlib.sha256(",".join(sorted(d.isoformat() for d in holidays)).encode()).hexdigest()[:12]


def is_business_day(d: dt.date, holidays: Holidays = frozenset()) -> bool:
    return d.weekday() < 5 and d not in holidays


def add_business_days(start: dt.date, n: int, holidays: Holidays = frozenset()) -> dt.date:
    """The date `n` business days after `start` (the start day itself is day 0)."""
    d = start
    remaining = n
    while remaining > 0:
        d += dt.timedelta(days=1)
        if is_business_day(d, holidays):
            remaining -= 1
    return d
