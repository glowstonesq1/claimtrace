"""Recognise amendment instructions and apply them across documents.

Original commitments are never overwritten: they are marked replaced/deleted and linked
to the amending text with `supersedes` edges (design-review D1/D2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SEC = r"(?:clause|section|paragraph|article)\s+(?P<sec>\d+(?:\.\d+)*(?:\s*\([a-z0-9]+\))*)"
_OF = r"(?:\s+of\s+(?:the\s+)?(?:[A-Z][\w ]{1,60}?|agreement|contract))?"
_QUOTE = r"[\"“](?P<new>[^\"”]{5,2000})[\"”]"

REPLACE_RE = re.compile(
    rf"{_SEC}{_OF}\s+(?:is|shall\s+be)\s+(?:hereby\s+)?(?:deleted\s+(?:in\s+its\s+entirety\s+)?and\s+replaced\s+(?:with|by)|"
    rf"amended\s+(?:to\s+read|so\s+as\s+to\s+read|as\s+follows)|replaced\s+(?:in\s+its\s+entirety\s+)?(?:with|by)|"
    rf"restated\s+(?:to\s+read|as\s+follows))(?:\s+the\s+following)?(?:\s+(?:new\s+)?(?:clause|section)\s+[\d.]+)?\s*:?\s*{_QUOTE}",
    re.I,
)
INSERT_RE = re.compile(
    rf"(?:the\s+following|a\s+new)\s+(?:new\s+)?(?:clause|section|paragraph)?\s*(?:is|shall\s+be)\s+(?:hereby\s+)?"
    rf"(?:added|inserted)(?:\s+(?:to|into)\s+(?:the\s+)?\w+)?\s+as\s+(?:a\s+new\s+)?(?:clause|section|paragraph)\s+"
    rf"(?P<sec>\d+(?:\.\d+)*)\s*:?\s*{_QUOTE}",
    re.I,
)
INSERT_RE2 = re.compile(
    rf"(?:a\s+new\s+)?(?:clause|section)\s+(?P<sec>\d+(?:\.\d+)*)\s+(?:is|shall\s+be)\s+(?:hereby\s+)?(?:added|inserted)"
    rf"[^:\"“]{{0,60}}:?\s*{_QUOTE}",
    re.I,
)
DELETE_RE = re.compile(
    rf"{_SEC}{_OF}\s+(?:is|shall\s+be)\s+(?:hereby\s+)?(?:deleted|removed|struck)(?:\s+in\s+its\s+entirety)?"
    rf"(?:\s+and\s+(?:shall\s+)?(?:have\s+no\s+further\s+effect|is\s+of\s+no\s+further\s+effect))?\s*(?:\.|$)",
    re.I,
)
MODIFY_RE = re.compile(
    rf"in\s+{_SEC}{_OF},?\s+(?:the\s+)?(?:reference\s+to|words?|figure|number|amount)\s+[\"“]?(?P<old>[^\"”]{{1,80}}?)[\"”]?\s+"
    rf"(?:is|are|shall\s+be)\s+(?:hereby\s+)?(?:replaced|substituted|amended)\s+(?:with|by|to)\s+[\"“]?(?P<new2>[^\"”]{{1,80}}?)[\"”]?"
    rf"\s*(?:\.|$)",
    re.I,
)
MODIFY_RE2 = re.compile(
    rf"(?:the\s+)?(?:reference\s+to|words?|figure)\s+[\"“]?(?P<old>[^\"”]{{1,80}}?)[\"”]?\s+in\s+{_SEC}{_OF}\s+"
    rf"(?:is|are|shall\s+be)\s+(?:hereby\s+)?(?:replaced|substituted|amended)\s+(?:with|by|to)\s+[\"“]?(?P<new2>[^\"”]{{1,80}}?)[\"”]?"
    rf"\s*(?:\.|$)",
    re.I,
)


@dataclass
class Instruction:
    target: str
    action: str  # replace | delete | insert | modify
    new_text: str | None
    start: int
    end: int
    new_start: int | None = None
    new_end: int | None = None
    old_text: str | None = None


def _sec(s: str) -> str:
    return re.sub(r"\s+", "", s)


def parse_instructions(text: str) -> list[Instruction]:
    out: list[Instruction] = []
    taken: list[tuple[int, int]] = []

    def add(ins: Instruction) -> None:
        if not any(a <= ins.start < b for a, b in taken):
            taken.append((ins.start, ins.end))
            out.append(ins)

    for rx, action in ((REPLACE_RE, "replace"), (INSERT_RE, "insert"), (INSERT_RE2, "insert")):
        for m in rx.finditer(text):
            add(Instruction(_sec(m["sec"]), action, m["new"].strip(), m.start(), m.end(), m.start("new"), m.end("new")))
    for rx in (MODIFY_RE, MODIFY_RE2):
        for m in rx.finditer(text):
            add(Instruction(_sec(m["sec"]), "modify", m["new2"].strip(), m.start(), m.end(), old_text=m["old"].strip()))
    for m in DELETE_RE.finditer(text):
        add(Instruction(_sec(m["sec"]), "delete", None, m.start(), m.end()))
    return sorted(out, key=lambda i: i.start)
