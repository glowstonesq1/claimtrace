"""Text normalisation, quote verification and tokenisation shared by every module.

Normalised text is computed once at ingestion and stored; all offsets index into it
(design-review D9). Bump NORMALIZER_VERSION whenever `normalize` changes output.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

NORMALIZER_VERSION = "norm-1"

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


def normalize(text: str) -> str:
    """NFKC, straight quotes, no soft hyphens, single spaces, paragraph breaks kept."""
    text = unicodedata.normalize("NFKC", text)
    for a, b in _REPLACEMENTS.items():
        text = text.replace(a, b)
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
_SENT_SPLIT = re.compile(r"(?<=[.;!?])\s+(?=[A-Z(\"])")


def sentences_with_offsets(text: str) -> list[tuple[int, int, str]]:
    """Split a passage into sentences, returning (start, end, sentence) offsets."""
    out: list[tuple[int, int, str]] = []
    start = 0
    for m in _SENT_SPLIT.finditer(text):
        before = text[start : m.start()]
        # don't split after abbreviations ("Co.") or clause numbers ("clause 2.")
        if _ABBREV.search(before) or re.search(r"\b\d+\.$", before):
            continue
        seg = text[start : m.start()]
        if seg.strip():
            out.append((start, m.start(), seg))
        start = m.end()
    if text[start:].strip():
        out.append((start, len(text), text[start:]))
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
