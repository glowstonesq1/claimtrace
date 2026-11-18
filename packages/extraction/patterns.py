"""Deterministic recognisers for parties, modal verbs, deadlines, conditions and references.

Each function is pure (text in, structured data out), so it is easy to unit-test and extend.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from claimtrace.core.models import Deadline, Modality

# --------------------------------------------------------------------- parties
ROLE_WORDS = {
    "customer",
    "vendor",
    "supplier",
    "client",
    "provider",
    "service provider",
    "contractor",
    "subcontractor",
    "licensor",
    "licensee",
    "buyer",
    "seller",
    "purchaser",
    "company",
    "consultant",
    "agency",
    "processor",
    "controller",
    "landlord",
    "tenant",
    "employer",
    "employee",
    "partner",
    "auditor",
    "lessor",
    "lessee",
    "distributor",
    "reseller",
    "manufacturer",
    "operator",
    "owner",
    "principal",
    "agent",
    "council",
    "authority",
    "hospital",
    "trust",
    "school",
    "university",
    "member",
    "recipient",
    "discloser",
    "disclosing party",
    "receiving party",
    "sponsor",
    "grantee",
    "grantor",
    "carrier",
    "shipper",
    "developer",
    "publisher",
    "host",
    "user",
    "insurer",
    "insured",
    "guarantor",
    "borrower",
    "lender",
}
COMPANY_SUFFIX = re.compile(
    r"\b(?:Ltd|Limited|Inc|LLC|LLP|L\.L\.C|Corp|Corporation|Co|Company|GmbH|AG|S\.A|SAS|BV|B\.V|plc|PLC|Pty|"
    r"Group|Holdings|Partners|Trust|Council|Authority|Foundation|Association|University|Hospital|NHS)\b\.?"
)
_DEFINED = re.compile(r"\((?:together,?\s+)?(?:each\s+)?(?:the\s+|a\s+)?[\"'](?P<alias>[A-Z][\w &\-]{0,40})[\"']\)")
COLLECTIVE = {
    "either party": "Either party",
    "each party": "Each party",
    "both parties": "Both parties",
    "the parties": "The parties",
    "neither party": "Neither party",
}


@dataclass
class PartyDef:
    name: str
    alias: str
    start: int
    end: int


def find_party_definitions(text: str) -> list[PartyDef]:
    """`Acme Ltd (the "Supplier")` → PartyDef(name="Acme Ltd", alias="Supplier")."""
    out: list[PartyDef] = []
    for m in _DEFINED.finditer(text):
        alias = m.group("alias").strip()
        before = text[: m.start()].rstrip().rstrip(",")
        words = before.split(" ")
        name_words: list[str] = []
        for w in reversed(words):
            if w and (w[0].isupper() or w[0].isdigit() or w in ("&", "of", "and", "de", "von", "&amp;")):
                name_words.insert(0, w)
                if len(name_words) > 8:
                    break
            else:
                break
        while name_words and name_words[0].lower() in ("of", "and", "&", "between", "by", "this", "the"):
            name_words.pop(0)
        name = " ".join(name_words).strip(" ,")
        is_party = bool(name) and (COMPANY_SUFFIX.search(name) is not None or alias.lower() in ROLE_WORDS)
        if is_party:
            out.append(PartyDef(name=name, alias=alias, start=m.start() - len(name) - 1, end=m.end()))
    return out


# --------------------------------------------------------------------- modals
_MODAL_PHRASES: list[tuple[str, Modality]] = [
    (
        r"shall\s+not|must\s+not|will\s+not|may\s+not|cannot|can\s*not|is\s+not\s+permitted\s+to|are\s+not\s+permitted\s+to"
        r"|is\s+prohibited\s+from|are\s+prohibited\s+from|agrees\s+not\s+to|undertakes\s+not\s+to|shall\s+refrain\s+from"
        r"|shall\s+in\s+no\s+event|will\s+never|shall\s+never",
        Modality.must_not,
    ),
    (
        r"shall\s+use\s+(?:all\s+)?(?:commercially\s+)?(?:reasonable|best|its\s+best|its\s+reasonable)\s+(?:endeavours|efforts|endeavors)"
        r"|will\s+use\s+(?:all\s+)?(?:commercially\s+)?(?:reasonable|best)\s+(?:endeavours|efforts|endeavors)"
        r"|shall\s+endeavour|will\s+endeavour|shall\s+endeavor|will\s+endeavor",
        Modality.reasonable_efforts,
    ),
    (
        r"is\s+entitled\s+to|are\s+entitled\s+to|shall\s+be\s+entitled\s+to|will\s+be\s+entitled\s+to|may"
        r"|has\s+the\s+right\s+to|have\s+the\s+right\s+to|reserves\s+the\s+right\s+to|is\s+permitted\s+to"
        r"|are\s+permitted\s+to",
        Modality.may,
    ),
    (
        r"shall|must|will|agrees\s+to|agree\s+to|undertakes\s+to|undertake\s+to|is\s+responsible\s+for"
        r"|are\s+responsible\s+for|shall\s+be\s+responsible\s+for|is\s+required\s+to|are\s+required\s+to"
        r"|is\s+obliged\s+to|is\s+obligated\s+to|covenants\s+to|commits\s+to|warrants\s+that|shall\s+procure\s+that",
        Modality.must,
    ),
]
# "Clause 6.1 does not apply where ..." has no modal verb but is a condition on another clause.
CONDITION_SENTENCE_RE = re.compile(
    r"^(?P<subj>(?:the\s+)?(?:clauses?|sections?|paragraphs?)\s+[\d.()a-z]+(?:\s+(?:and|or)\s+[\d.()a-z]+)?)\s+"
    r"(?P<modal>(?:does|do|shall|will)\s+not\s+apply|(?:is|are)\s+subject\s+to|(?:applies|apply)\s+only)\b",
    re.I,
)
MODAL_RE = re.compile(r"\b(?P<modal>" + "|".join(f"(?:{p})" for p, _ in _MODAL_PHRASES) + r")\b", re.IGNORECASE)


def modality_of(phrase: str) -> Modality:
    p = re.sub(r"\s+", " ", phrase.lower())
    for pattern, mod in _MODAL_PHRASES:
        if re.fullmatch(pattern, p):
            return mod
    return Modality.must


PASSIVE_RE = re.compile(
    r"^\s*(?:shall|must|will)\s+(?:not\s+)?be\s+(?P<verb>\w+ed|given|paid|sent|made|done|kept|held|"
    r"provided|delivered|issued|taken|set|sent|borne|met|completed|submitted|carried)\b",
    re.I,
)
NON_OBLIGATION_VERBS = re.compile(
    r"^\s*(?:shall|will|may)\s+(?:be\s+)?(?:governed|construed|interpreted|deemed|"
    r"continue|remain|survive|apply|commence|take\s+effect|prevail|mean|include|be\s+read)\b",
    re.I,
)

# --------------------------------------------------------------------- dates & deadlines
MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9
_MON = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"  # noqa: E501
DATE_PATTERNS = [
    (re.compile(rf"\b(?P<mon>{_MON})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>\d{{4}})\b", re.I), "mdy"),
    (re.compile(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<mon>{_MON})\.?,?\s+(?P<y>\d{{4}})\b", re.I), "dmy"),
    (re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b"), "iso"),
    (re.compile(r"\b(?P<a>\d{1,2})[/.](?P<b>\d{1,2})[/.](?P<y>\d{4})\b"), "slash"),
]


def _month(name: str) -> int:
    n = name.lower().rstrip(".")
    return MONTHS.get(n) or MONTHS[n[:3]]


@dataclass
class FoundDate:
    start: int
    end: int
    raw: str
    date: dt.date | None
    ambiguous: bool


def find_dates(text: str) -> list[FoundDate]:
    out: list[FoundDate] = []
    taken: list[tuple[int, int]] = []
    for rx, kind in DATE_PATTERNS:
        for m in rx.finditer(text):
            if any(s <= m.start() < e for s, e in taken):
                continue
            ambiguous = False
            try:
                if kind in ("mdy", "dmy"):
                    d = dt.date(int(m["y"]), _month(m["mon"]), int(m["d"]))
                elif kind == "iso":
                    d = dt.date(int(m["y"]), int(m["m"]), int(m["d"]))
                else:
                    a, b = int(m["a"]), int(m["b"])
                    if a > 12 and b <= 12:
                        d = dt.date(int(m["y"]), b, a)
                    elif b > 12 and a <= 12:
                        d = dt.date(int(m["y"]), a, b)
                    else:
                        d = None if a != b else dt.date(int(m["y"]), a, b)
                        ambiguous = a != b
            except (ValueError, KeyError):
                d, ambiguous = None, True
            taken.append((m.start(), m.end()))
            out.append(FoundDate(m.start(), m.end(), m.group(0), d, ambiguous))
    return sorted(out, key=lambda f: f.start)


_NUMWORDS = {
    w: i
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
        "seventeen eighteen nineteen twenty".split()
    )
}
_NUMWORDS.update(
    {"thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90, "hundred": 100, "a": 1, "an": 1}
)
_NUM = r"(?:\d+|" + "|".join(sorted((re.escape(k) for k in _NUMWORDS), key=len, reverse=True)) + r")"
RELATIVE_RE = re.compile(
    rf"\b(?:within|no\s+later\s+than|not\s+later\s+than|not\s+more\s+than|at\s+least|before\s+the\s+expiry\s+of|"
    rf"by\s+no\s+later\s+than|on\s+or\s+before\s+the\s+date\s+falling)?\s*(?P<n>{_NUM})\s*(?:\((?:\d+)\)\s*)?"
    rf"(?P<unit_kind>business|working|calendar|banking)?\s*(?P<unit>hours?|days?|weeks?|months?|years?)['’]?"
    rf"(?:\s+(?:written\s+)?notice)?"
    rf"(?:\s+(?P<rel>of|after|from|following|before|prior\s+to|following\s+receipt\s+of|of\s+receipt\s+of)\s+"
    rf"(?P<anchor>[^,;.]{{3,80}}))?",
    re.I,
)
RECURRING_RE = re.compile(
    r"\b(?:weekly|monthly|quarterly|annually|yearly|daily|fortnightly|biannually|semi-annually|"
    r"(?:each|every|in\s+each|once\s+(?:a|per|every))\s+(?:calendar\s+)?(?:day|week|month|quarter|year|business\s+day))\b",
    re.I,
)
VAGUE_RE = re.compile(
    r"\b(?:promptly|as\s+soon\s+as\s+(?:reasonably\s+)?(?:practicable|possible)|without\s+undue\s+delay|"
    r"in\s+a\s+timely\s+(?:manner|fashion)|timely|forthwith|in\s+due\s+course|within\s+a\s+reasonable\s+(?:time|period)|"
    r"at\s+the\s+earliest\s+opportunity|from\s+time\s+to\s+time|immediately)\b",
    re.I,
)
DEADLINE_PREP = re.compile(
    r"\b(?:no\s+later\s+than|not\s+later\s+than|on\s+or\s+before|by|before|until|prior\s+to|"
    r"on|not\s+after|in\s+any\s+event\s+by)\s*$",
    re.I,
)


def _num(s: str) -> int | None:
    s = s.lower()
    return int(s) if s.isdigit() else _NUMWORDS.get(s)


def extract_deadline(sentence: str, reference_date: dt.date | None = None) -> Deadline:
    """Classify timing in one sentence. Dates are computed only when the anchor resolves."""
    for fd in find_dates(sentence):
        pm = DEADLINE_PREP.search(sentence[: fd.start])
        if pm:
            return Deadline(
                kind="absolute", raw=sentence[pm.start() : fd.end].strip(), date=fd.date, ambiguous_format=fd.ambiguous
            )
    m = None
    for cand in RELATIVE_RE.finditer(sentence):
        if cand.group("unit") and _num(cand.group("n")) is not None:
            prefix = sentence[max(0, cand.start() - 25) : cand.start() + 12].lower()
            if re.search(
                r"within|later than|notice|after|before|following|at least|not more than|period of",
                prefix + cand.group(0).lower(),
            ):
                m = cand
                break
    if m:
        n = _num(m.group("n")) or 0
        unit = m.group("unit").lower().rstrip("s")
        business = (m.group("unit_kind") or "").lower() in ("business", "working", "banking")
        factor = {"day": 1, "week": 7}.get(unit)
        offset = n * factor if factor else None
        anchor = m.group("anchor").strip() if m.group("anchor") else None
        date = None
        if (
            anchor
            and reference_date
            and offset is not None
            and not business
            and re.search(r"date of this (?:agreement|contract)|effective date|commencement date", anchor, re.I)
        ):
            date = reference_date + dt.timedelta(days=offset)
        return Deadline(
            kind="relative", raw=m.group(0).strip(), offset_days=offset, business_days=business, anchor=anchor, date=date
        )
    rec = RECURRING_RE.search(sentence)
    if rec:
        return Deadline(kind="recurring", raw=rec.group(0))
    vague = VAGUE_RE.search(sentence)
    if vague:
        return Deadline(kind="vague", raw=vague.group(0))
    for fd in find_dates(sentence):  # a date without a deadline preposition: keep it, but as raw context
        return Deadline(kind="absolute", raw=fd.raw, date=fd.date, ambiguous_format=fd.ambiguous)
    return Deadline(kind="none")


# --------------------------------------------------------------------- conditions, exceptions, references
CONDITION_RE = re.compile(
    r"\b(?P<kw>if|where|provided\s+that|providing\s+that|on\s+condition\s+that|subject\s+to|upon|in\s+the\s+event\s+(?:that|of)|"
    r"once|conditional\s+(?:up)?on|following|after)\b(?P<body>[^;]{3,200}?)(?=,|;|\.$|$| then\b)",
    re.I,
)
EXCEPTION_RE = re.compile(
    r"\b(?P<kw>except|excluding|unless|save\s+that|save\s+as|save\s+for|other\s+than|notwithstanding|"
    r"without\s+(?:the\s+)?(?:[\w']+\s+){0,3}(?:prior\s+)?(?:written\s+)?(?:consent|approval|agreement))\b"
    r"(?P<body>[^;]{0,200}?)(?=;|\.$|$)",
    re.I,
)
REFERENCE_RE = re.compile(
    r"\b(?:clauses?|sections?|paragraphs?|schedules?|annex(?:es)?|appendix|articles?)\s+"
    r"(?P<ref>\d+(?:\.\d+)*(?:\s*\([a-z0-9]+\))*|[A-Z]\b)",
    re.I,
)
QUALIFIER_RE = re.compile(
    r"\b(?:except|unless|subject\s+to|notwithstanding|provided\s+that|save\s+that|save\s+as|"
    r"however|does\s+not\s+apply|shall\s+not\s+apply|other\s+than|excluding|in\s+no\s+event)\b",
    re.I,
)


def find_conditions(sentence: str) -> list[str]:
    out = []
    for m in CONDITION_RE.finditer(sentence):
        kw = m.group("kw").lower()
        if kw in ("following", "after", "upon") and not sentence[: m.start()].strip() == "":
            continue  # "after" mid-sentence is usually part of a deadline ("30 days after receipt")
        if kw == "subject to":
            continue  # treated as an exception/override below
        out.append((m.group("kw") + m.group("body")).strip())
    return out


def find_exceptions(sentence: str) -> list[str]:
    out = [(m.group("kw") + m.group("body")).strip() for m in EXCEPTION_RE.finditer(sentence)]
    out += [m.group(0).strip() for m in re.finditer(r"\bsubject\s+to\s+[^,;.]{2,80}", sentence, re.I)]
    return out


def find_references(sentence: str) -> list[str]:
    return [re.sub(r"\s+", "", m.group("ref")) for m in REFERENCE_RE.finditer(sentence)]


# --------------------------------------------------------------------- quantities (used by verification)
AMOUNT_RE = re.compile(
    r"(?P<cur>GBP|USD|EUR|CAD|AUD|INR|£|\$|€)\s?(?P<num>\d[\d,]*(?:\.\d+)?)(?:\s?(?P<mult>k|m|million|thousand))?"
    r"|(?P<num2>\d[\d,]*(?:\.\d+)?)\s?(?P<cur2>GBP|USD|EUR|dollars|pounds|euros)",
    re.I,
)
PERCENT_RE = re.compile(r"(?P<num>\d+(?:\.\d+)?)\s?(?:%|per\s?cent|percent)", re.I)
DURATION_RE = re.compile(
    rf"(?P<n>{_NUM})\s*(?:\(\d+\)\s*)?(?P<kind>business\s+|working\s+|calendar\s+)?"
    rf"(?P<unit>hours?|days?|weeks?|months?|years?)\b",
    re.I,
)


def amounts(text: str) -> list[float]:
    out = []
    for m in AMOUNT_RE.finditer(text):
        num = (m.group("num") or m.group("num2") or "0").replace(",", "")
        val = float(num)
        mult = (m.group("mult") or "").lower()
        val *= {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6}.get(mult, 1)
        out.append(val)
    return out


def percents(text: str) -> list[float]:
    return [float(m.group("num")) for m in PERCENT_RE.finditer(text)]


def durations(text: str) -> list[tuple[int, str]]:
    """(value, unit) normalised to hours for hours, days otherwise."""
    out = []
    for m in DURATION_RE.finditer(text):
        n = _num(m.group("n"))
        if n is None:
            continue
        unit = m.group("unit").lower().rstrip("s")
        if unit == "hour":
            out.append((n, "hour"))
        elif unit in ("day", "week"):
            kind = "bday" if (m.group("kind") or "").strip().lower() in ("business", "working") else "day"
            out.append((n * (7 if unit == "week" else 1), kind))
        else:
            out.append((n, unit))
    return out
