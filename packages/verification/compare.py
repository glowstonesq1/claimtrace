"""Typed comparison of a commitment against a passage or claim from another document.

Field-level checks (dates, amounts, percentages, durations, places, negation) come first;
anything they cannot decide falls to needs_human_review rather than "consistent" (D24).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from claimtrace.core.models import Commitment, CommitmentType, Modality, Verdict
from claimtrace.core.text import tokens
from claimtrace.extraction import patterns as P

PLACES = {
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "england": "United Kingdom",
    "london": "United Kingdom",
    "scotland": "United Kingdom",
    "wales": "United Kingdom",
    "manchester": "United Kingdom",
    "ireland": "Ireland",
    "dublin": "Ireland",
    "germany": "Germany",
    "frankfurt": "Germany",
    "berlin": "Germany",
    "france": "France",
    "paris": "France",
    "netherlands": "Netherlands",
    "amsterdam": "Netherlands",
    "united states": "United States",
    "usa": "United States",
    "virginia": "United States",
    "california": "United States",
    "oregon": "United States",
    "canada": "Canada",
    "toronto": "Canada",
    "india": "India",
    "mumbai": "India",
    "singapore": "Singapore",
    "australia": "Australia",
    "sydney": "Australia",
    "japan": "Japan",
    "tokyo": "Japan",
    "spain": "Spain",
    "madrid": "Spain",
    "italy": "Italy",
    "sweden": "Sweden",
    "stockholm": "Sweden",
    "switzerland": "Switzerland",
    "zurich": "Switzerland",
    "poland": "Poland",
    "belgium": "Belgium",
    "brussels": "Belgium",
    "brazil": "Brazil",
    "mexico": "Mexico",
    "china": "China",
}
REGIONS = {
    "european union": {"Ireland", "Germany", "France", "Netherlands", "Spain", "Italy", "Sweden", "Poland", "Belgium"},
    "eea": {"Ireland", "Germany", "France", "Netherlands", "Spain", "Italy", "Sweden", "Poland", "Belgium"},
}
_PLACE_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(k) for k in [*PLACES, *REGIONS]), key=len, reverse=True)) + r")\b", re.I
)
EXCEPTION_WORDS = re.compile(r"\b(?:except|however|but|other\s+than|apart\s+from|with\s+the\s+exception)\b", re.I)
NEGATIVE = re.compile(
    r"\b(?:not|no|without|never|failed|fails|missing|absent|lacked|lacking|exception|except|"
    r"however|but|were\s+found|was\s+found|did\s+not|does\s+not|has\s+not|have\s+not|"
    r"outstanding|overdue|late|breach(?:ed)?|deficien\w*|gap)\b",
    re.I,
)
SCOPE_LIMIT = re.compile(
    r"\b(?:did\s+not\s+(?:test|review|assess|examine|cover)|not\s+(?:tested|reviewed|assessed|"
    r"examined|in\s+scope)|no\s+opinion|out\s+of\s+scope|outside\s+(?:the\s+)?scope|excluded\s+from)\b",
    re.I,
)
HIGHER_IS_BETTER = re.compile(
    r"\b(?:availab\w*|uptime|accuracy|coverage|at\s+least|minimum|not\s+less\s+than|"
    r"satisfaction|success)\b",
    re.I,
)
GENERIC = set(
    tokens(
        "shall must will may party parties agreement contract customer vendor supplier client provider "
        "document report section clause all any each such other services service system data "
        "ensure provide maintain use within days months writing written"
    )
)


def places(text: str) -> set[str]:
    out: set[str] = set()
    for m in _PLACE_RE.finditer(text):
        k = m.group(1).lower()
        if k in REGIONS:
            out.add(k.upper() if k == "eea" else "European Union")
        else:
            out.add(PLACES[k])
    return out


def topic_overlap(a: str, b: str, extra_generic: set[str] | None = None) -> tuple[float, list[str]]:
    generic = GENERIC | (extra_generic or set())
    ta = {t for t in tokens(a) if t not in generic and not t.isdigit()}
    tb = {t for t in tokens(b) if t not in generic and not t.isdigit()}
    if not ta:
        return 0.0, []
    shared = sorted(ta & tb)
    return len(shared) / len(ta), shared


@dataclass
class Comparison:
    verdict: Verdict
    explanation: str
    fields: list[str] = field(default_factory=list)  # which typed fields drove the verdict


def _fmt(x: float) -> str:
    return f"{x:,.0f}" if x == int(x) else f"{x:,}"


def compare_values(commitment: Commitment, other: str, evidence_mode: bool) -> Comparison | None:
    """Field-level comparison. Returns None when no comparable field exists."""
    ctext = commitment.text
    if evidence_mode and SCOPE_LIMIT.search(other):
        return Comparison(
            Verdict.not_addressed,
            "The other document says this was not examined, so it neither supports nor contradicts the commitment.",
            ["scope"],
        )
    # dates: deadline vs event date
    if commitment.deadline and commitment.deadline.date:
        other_dates = [d.date for d in P.find_dates(other) if d.date]
        if other_dates:
            event = max(other_dates)
            due = commitment.deadline.date
            if evidence_mode:
                if event > due:
                    return Comparison(
                        Verdict.contradicted,
                        f"Done on {event:%d %b %Y}, after the deadline of {due:%d %b %Y} ({(event - due).days} days late).",
                        ["date"],
                    )
                return Comparison(
                    Verdict.consistent, f"Dated {event:%d %b %Y}, on or before the deadline of {due:%d %b %Y}.", ["date"]
                )
            if event != due:
                return Comparison(Verdict.contradicted, f"Date differs: {due:%d %b %Y} vs {event:%d %b %Y}.", ["date"])
            return Comparison(Verdict.consistent, f"Same date: {due:%d %b %Y}.", ["date"])
    # percentages
    cp, op = P.percents(ctext), P.percents(other)
    if cp and op:
        a, b = cp[0], op[0]
        if a == b:
            return Comparison(Verdict.consistent, f"Same percentage ({a}%).", ["percent"])
        if evidence_mode and HIGHER_IS_BETTER.search(ctext + " " + other):
            if b >= a:
                return Comparison(Verdict.consistent, f"Measured {b}% meets the committed {a}%.", ["percent"])
            return Comparison(Verdict.contradicted, f"Measured {b}% is below the committed {a}%.", ["percent"])
        return Comparison(Verdict.contradicted, f"Percentage differs: {a}% vs {b}%.", ["percent"])
    # amounts
    ca, oa = P.amounts(ctext), P.amounts(other)
    if ca and oa:
        if ca[0] == oa[0]:
            return Comparison(Verdict.consistent, f"Same amount ({_fmt(ca[0])}).", ["amount"])
        if evidence_mode and re.search(r"\b(?:at\s+least|minimum|not\s+less\s+than)\b", ctext, re.I) and oa[0] >= ca[0]:
            return Comparison(Verdict.consistent, f"{_fmt(oa[0])} meets the minimum of {_fmt(ca[0])}.", ["amount"])
        return Comparison(Verdict.contradicted, f"Amount differs: {_fmt(ca[0])} vs {_fmt(oa[0])}.", ["amount"])
    # durations ("within 48 hours" vs "within 72 hours")
    cd, od = P.durations(ctext), P.durations(other)
    if cd and od:
        (cn, cu), (on, ou) = cd[0], od[0]
        if cu == ou:
            if cn == on:
                anchor_c = commitment.deadline.anchor if commitment.deadline else None
                m = re.search(
                    r"\b(?:of|after|from|following)\s+([^,.;]{3,60})",
                    other[other.lower().find(str(on)) :] if str(on) in other else other,
                )
                anchor_o = m.group(1) if m else None
                if anchor_c and anchor_o:
                    ov, _ = topic_overlap(anchor_c, anchor_o)
                    if ov < 0.5:
                        return Comparison(
                            Verdict.needs_human_review,
                            f"Same period ({cn} {cu}s) but a different starting point: "
                            f'"{anchor_c}" vs "{anchor_o}". The clock may start later.',
                            ["duration", "anchor"],
                        )
                return Comparison(Verdict.consistent, f"Same period ({cn} {cu}s).", ["duration"])
            if evidence_mode and on < cn:
                return Comparison(Verdict.consistent, f"{on} {ou}s is within the committed {cn} {cu}s.", ["duration"])
            return Comparison(Verdict.contradicted, f"Period differs: {cn} vs {on} {cu}s.", ["duration"])
    # places
    cpl, opl = places(ctext), places(other)
    if cpl and opl:
        allowed = set(cpl)
        for r, members in REGIONS.items():
            if r in ctext.lower() or ("european union" in ctext.lower() and r == "european union"):
                allowed |= members
        if opl <= allowed:
            return Comparison(Verdict.consistent, f"Location matches ({', '.join(sorted(opl))}).", ["place"])
        return Comparison(
            Verdict.contradicted,
            f"Location differs: commitment refers to {', '.join(sorted(cpl))}; other document says {', '.join(sorted(opl))}.",
            ["place"],
        )
    # modality / polarity (contract vs contract)
    if not evidence_mode:
        om = P.MODAL_RE.search(other)
        if om:
            omod = P.modality_of(om.group("modal"))
            if omod != commitment.modality and {omod, commitment.modality} != {Modality.must, Modality.reasonable_efforts}:
                return Comparison(
                    Verdict.contradicted,
                    f"Obligation strength differs: '{commitment.modality.value}' vs '{omod.value}'.",
                    ["modality"],
                )
            if omod != commitment.modality:
                return Comparison(
                    Verdict.partially_supported,
                    "One text is an absolute duty, the other only requires reasonable efforts.",
                    ["modality"],
                )
    return None


def judge(commitment: Commitment, candidates: list[str], evidence_mode: bool) -> Comparison:
    """Combine typed comparisons over all candidate texts for one commitment."""
    results = [compare_values(commitment, c, evidence_mode) for c in candidates]
    typed = [r for r in results if r is not None]
    verdicts = {r.verdict for r in typed}
    if Verdict.contradicted in verdicts:
        return next(r for r in typed if r.verdict == Verdict.contradicted)
    if Verdict.needs_human_review in verdicts:
        return next(r for r in typed if r.verdict == Verdict.needs_human_review)
    negatives = [c for c in candidates if NEGATIVE.search(c) and not SCOPE_LIMIT.search(c)]
    positives = [c for c in candidates if c not in negatives and not SCOPE_LIMIT.search(c)]
    mixed = [c for c in negatives if EXCEPTION_WORDS.search(c)]  # "done, except for ..." is partial, not failure
    if negatives and (positives or Verdict.consistent in verdicts or mixed):
        return Comparison(
            Verdict.partially_supported,
            "Part of the commitment is supported, but the other document also reports an exception "
            f'or gap: "{negatives[0][:160]}"',
            ["negation"],
        )
    if Verdict.not_addressed in verdicts and not positives:
        return next(r for r in typed if r.verdict == Verdict.not_addressed)
    if negatives and not positives:
        if commitment.modality == Modality.must_not or commitment.type == CommitmentType.prohibition:
            return Comparison(
                Verdict.needs_human_review, "Both texts contain negative wording; check whether they agree.", ["negation"]
            )
        return Comparison(
            Verdict.contradicted, f'The other document reports a failure or gap: "{negatives[0][:160]}"', ["negation"]
        )
    if Verdict.consistent in verdicts:
        return next(r for r in typed if r.verdict == Verdict.consistent)
    if evidence_mode:
        return Comparison(Verdict.consistent, "Matching text was located in the other document.", ["topic"])
    return Comparison(Verdict.consistent, "The other document states the same commitment.", ["topic"])
