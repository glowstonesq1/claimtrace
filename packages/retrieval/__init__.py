"""Lexical retrieval (BM25) with light query expansion. Dense/hybrid retrieval is planned for v0.2,
once the eval logs where lexical retrieval fails (design-review backlog P2)."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from claimtrace.core.text import stem, tokens

EXPANSIONS = {
    "uk": "united kingdom",
    "u.k": "united kingdom",
    "britain": "united kingdom",
    "us": "united states",
    "usa": "united states",
    "eu": "european union",
    "mfa": "multi factor authentication",
    "2fa": "multi factor authentication",
    "sla": "service level",
    "pentest": "penetration test",
    "pen": "penetration",
    "pay": "payment",
    "paid": "payment",
    "invoice": "invoices",
    "late": "delay",
    "deadline": "no later than",
    "due": "no later than",
    "uptime": "availability",
    "breach": "breach",
    "terminate": "termination",
    "cancel": "terminate",
    "kept": "hosted stored located",
    "stored": "hosted located",
    "located": "hosted stored",
    "delivery": "deliver",
    "delivered": "deliver",
    "misses": "fails",
    "miss": "fails",
}


def expand_query(text: str) -> list[str]:
    toks = tokens(text)
    extra: list[str] = []
    for raw in text.lower().replace("?", " ").split():
        key = raw.strip(".,;:'\"")
        if key in EXPANSIONS:
            extra += tokens(EXPANSIONS[key])
    return toks + extra


def term_groups(text: str, drop: set[str] | None = None) -> list[set[str]]:
    """One group per original query term: the term plus its expansions. Coverage counts groups, so
    expansion widens matching without inflating the denominator."""
    groups: list[set[str]] = []
    for raw in text.lower().replace("?", " ").split():
        key = raw.strip(".,;:'\"")
        base = tokens(key)
        if not base or (drop and base[0] in drop):
            continue
        g = set(base)
        if key in EXPANSIONS:
            g |= set(tokens(EXPANSIONS[key]))
        if g not in groups:
            groups.append(g)
    return groups


@dataclass
class Hit:
    id: str
    score: float
    coverage: float  # share of distinct query terms found in the item
    matched: list[str] = field(default_factory=list)


class BM25:
    def __init__(self, items: list[tuple[str, str]], k1: float = 1.4, b: float = 0.75) -> None:
        self.ids = [i for i, _ in items]
        self.docs = [tokens(t) for _, t in items]
        self.sets = [set(d) for d in self.docs]
        self.k1, self.b = k1, b
        self.avg = sum(len(d) for d in self.docs) / max(len(self.docs), 1)
        df: Counter[str] = Counter()
        for s in self.sets:
            df.update(s)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def search(self, query_terms: list[str], k: int = 5) -> list[Hit]:
        q = list(dict.fromkeys(query_terms))
        if not q:
            return []
        hits: list[Hit] = []
        for i, d in enumerate(self.docs):
            tf = Counter(d)
            score = 0.0
            matched = [t for t in q if t in self.sets[i]]
            for t in matched:
                f = tf[t]
                score += self.idf.get(t, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avg))
            if score > 0:
                hits.append(Hit(self.ids[i], score, len(matched) / len(q), matched))
        hits.sort(key=lambda h: (-h.score, -h.coverage))
        return hits[:k]


__all__ = ["BM25", "EXPANSIONS", "Hit", "expand_query", "stem", "term_groups", "tokens"]
