"""Text normalisation, quote verification and tokenisation shared by every module.

Normalised text is computed once at ingestion and stored; all offsets index into it
(design-review D9). Bump NORMALIZER_VERSION whenever `normalize` changes output.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

NORMALIZER_VERSION = "norm-2"  # norm-2: every Unicode whitespace collapses (ReDoS hardening)

_REPLACEMENTS = {
    " ": " ",
    " ": " ",
    " ": " ",
    "­": "",
    "​": "",
    "﻿": "",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "\r\n": "\n",
    "\r": "\n",
    "\t": " ",
}


# Line/paragraph separators other than "\n" (\v, \f, U+001C-U+001E, U+0085, U+2028) and U+2029.
_LINE_BREAKS = re.compile(r"[\v\f\x1c-\x1e\x85\u2028]")
_OTHER_SPACE = re.compile(r"[^\S\n]")  # every remaining Unicode whitespace character (U+1680, U+3000, ...)


def normalize(text: str) -> str:
    """NFKC, straight quotes, no soft hyphens, single spaces, paragraph breaks kept.

    Only " " and "\n" survive: exotic whitespace (U+1680, \v, \f, U+0085, ...) is collapsed too, so a long
    run of it cannot reach the extraction regexes (ReDoS hardening).
    """
    text = unicodedata.normalize("NFKC", text)
    for a, b in _REPLACEMENTS.items():
        text = text.replace(a, b)
    text = text.replace("\u2029", "\n\n")
    text = _LINE_BREAKS.sub("\n", text)
    text = _OTHER_SPACE.sub(" ", text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # de-hyphenate PDF line breaks
    paragraphs = re.split(r"\n\s*\n", text)
    out = []
    for p in paragraphs:
        p = re.sub(r"[ \n]+", " ", p).strip()
        if p:
            out.append(p)
    return "\n\n".join(out)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def squash(s: str) -> str:
    """Comparison form: lowercase, straight quotes, single spaces."""
    return re.sub(r"\s+", " ", normalize(s)).strip().lower()


def find_quote(haystack: str, quote: str) -> tuple[int, int] | None:
    """Exact location of `quote` in `haystack`, tolerant only of case and whitespace.

    This is the verbatim check (stage 1 of design-review D4). It never fuzzy-matches.
    """
    if not quote.strip():
        return None
    idx = haystack.find(quote)
    if idx >= 0:
        return idx, idx + len(quote)
    parts = [re.escape(p) for p in squash(quote).split(" ")]
    m = re.search(r"\s+".join(parts), haystack, flags=re.IGNORECASE)
    return (m.start(), m.end()) if m else None


_ABBREV = re.compile(r"\b(?:e\.g|i\.e|etc|Ltd|Inc|Co|No|Mr|Ms|Dr|St|vs|cl|para|Sch|art)\.$", re.I)
_CLAUSE_NO_END = re.compile(r"\b\d+\.$")
# a sentence ends at . ; ! ? before a capital, a bracket or a quote, or before a numbered clause ("1.2 The")
_SENT_SPLIT = re.compile(r"(?<=[.;!?])\s+(?=[A-Z(\"]|\d+(?:\.\d+)+\.?\s+[A-Z(\"])")
# Longest "sentence" handed to extraction. Real clauses are far shorter; text with no sentence breaks at all
# (a run-on export, a table flattened to one line) is cut at a word boundary so per-sentence work stays bounded
# and analysis time stays linear in document length.
MAX_SENTENCE_CHARS = 2000
_TAIL = 24  # enough to see the longest abbreviation or clause number before a split point


def _cut_long(start: int, seg: str, out: list[tuple[int, int, str]]) -> None:
    while len(seg) > MAX_SENTENCE_CHARS:
        window = seg[:MAX_SENTENCE_CHARS]
        cut = max(window.rfind("; "), window.rfind(", "))
        if cut < MAX_SENTENCE_CHARS // 2:
            cut = window.rfind(" ")
        cut = cut + 1 if cut > 0 else MAX_SENTENCE_CHARS
        if seg[:cut].strip():
            out.append((start, start + cut, seg[:cut]))
        start, seg = start + cut, seg[cut:]
    if seg.strip():
        out.append((start, start + len(seg), seg))


def sentences_with_offsets(text: str) -> list[tuple[int, int, str]]:
    """Split a passage into sentences, returning (start, end, sentence) offsets. Linear in len(text)."""
    out: list[tuple[int, int, str]] = []
    start = 0
    for m in _SENT_SPLIT.finditer(text):
        # don't split after abbreviations ("Co.") or clause numbers ("clause 2."); only the text just before the
        # split point matters, so look at a short tail rather than the whole (possibly huge) run since `start`
        tail = text[max(start, m.start() - _TAIL) : m.start()]
        if _ABBREV.search(tail) or _CLAUSE_NO_END.search(tail):
            continue
        _cut_long(start, text[start : m.start()], out)
        start = m.end()
    _cut_long(start, text[start:], out)
    return out


STOPWORDS = frozenset(
    """a an the and or of to in on at by for with from as is are was were be been being this that these those
    it its into than then there their them they we our us you your i me my he she his her what which who whom
    whose when where why how do does did done has have had having can could should would will shall may might
    must not no any all each either every other such same so if any about over under up down out off again
    further once only own too very just also per same both between within without upon whether""".split()
)

_SUFFIXES = tuple(
    sorted(
        (
            "abilities",
            "ability",
            "ables",
            "able",
            "ibility",
            "ible",
            "ications",
            "ication",
            "icated",
            "icate",
            "ations",
            "ation",
            "ated",
            "ates",
            "ate",
            "ating",
            "ments",
            "ment",
            "ness",
            "ings",
            "ing",
            "ities",
            "ity",
            "ies",
            "ied",
            "ers",
            "er",
            "ed",
            "sses",
            "ive",
            "ally",
            "al",
            "ly",
            "s",
            "y",
        ),
        key=len,
        reverse=True,
    )
)


def stem(word: str) -> str:
    """Suffix stripping applied until stable, so "deliver"/"delivered"/"delivery" share one stem."""
    w = word.lower()
    if w.isdigit():
        return w
    for _ in range(3):
        if len(w) <= 4:
            break
        for suf in _SUFFIXES:
            if w.endswith(suf) and len(w) - len(suf) >= 4:
                w = w[: -len(suf)]
                break
        else:
            break
    return w


_TOKEN = re.compile(r"[A-Za-z]+(?:'[a-z]+)?|\d+(?:[.,]\d+)*%?")


def tokens(text: str, keep_stopwords: bool = False) -> list[str]:
    out = []
    for t in _TOKEN.findall(text):
        tl = t.lower()
        if not keep_stopwords and tl in STOPWORDS:
            continue
        out.append(stem(tl))
    return out


INJECTION_RE = re.compile(
    r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+|your\s+|the\s+|previous\s+|prior\s+|above\s+)*"
    r"(?:instructions?|prompts?|rules?|guidelines?)\b|\bsystem\s+prompt\b|\byou\s+are\s+(?:now\s+)?(?:an?\s+|the\s+)?"
    r"(?:ai|assistant|language\s+model|llm|chatbot)\b|\b(?:as\s+an\s+ai|new\s+instructions?|developer\s+mode)\b|"
    r"\b(?:mark|report|classify|answer)\s+(?:all|every)\s+\w+\s+as\b",
    re.I,
)


def looks_like_injection(text: str) -> bool:
    """Heuristic for instruction-like text aimed at a model. Not a guarantee; see docs/security.md."""
    return INJECTION_RE.search(text) is not None
