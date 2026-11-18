"""Recognise amendment instructions in the text of an amending document.

Parsing is per passage and purely textual: it says *what* an instruction asks for (replace, delete,
insert, modify, renumber, restate) and *which* clause it names. Whether that clause exists, and what
the instruction does to it, is decided against the amended document in `apply.py`; an instruction whose
target cannot be found is flagged for human review there, never applied silently.

Original commitments are never overwritten: they are marked replaced/deleted and linked
to the amending text with `supersedes` edges (design-review D1/D2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .patterns import NUMBER_WORDS, number_words

# ------------------------------------------------------------------ building blocks
_N = r"\d+(?:\.\d+)*(?:\s*\([a-z0-9]{1,4}\))*"
_CL = r"(?:sub-?clauses?|clauses?|sections?|paragraphs?|articles?)"
_SCHED = r"(?:schedule|annex|appendix|exhibit)"
# "Clause 10 (Non-Solicitation)", "Clause 4.4 (as renumbered)" - the parenthesis is descriptive only
_PAREN = r"(?:\s*\((?:as\s+(?:re)?numbered|as\s+amended|[A-Z][^()\"“”]{1,60})\))?"
_OF = r"(?:\s+of\s+(?:the\s+|this\s+)?(?:[A-Z][\w ]{1,60}?|agreement|contract|deed))?"
_TARGET = (
    rf"(?:{_CL}\s+(?P<sec>{_N}){_PAREN}"
    rf"|(?P<sched>{_SCHED}\s+(?:\d+|[A-Z])\b)"
    rf"|(?:the\s+)?(?:clause|section|paragraph|article)\s+(?:headed|entitled|titled|named|called)\s+"
    rf"[\"“](?P<title>[^\"”]{{2,60}})[\"”]"
    rf"|the\s+[\"“](?P<title2>[^\"”]{{2,60}})[\"”]\s+(?:clause|section)\b(?!\s+\d)"
    rf"){_OF}"
)
_AUX = r"(?:(?:is|are|shall|will|should|must|is\s+to|are\s+to)\s+(?:be\s+)?)?(?:hereby\s+)?(?:now\s+)?"
_QUOTE = r"[\"“](?P<new>[^\"”]{2,3000})[\"”]"
_FOLLOW = r"(?P<follows>:\s*$)"  # the replacement text is in the next passage
_ENTIRE = r"(?:\s+in\s+(?:its|their)\s+entirety)?"


def _val(name: str) -> str:
    """A quoted phrase, or a short unquoted one ("90 days", "99.5%")."""
    return rf"(?:[\"“](?P<{name}>[^\"”]{{0,200}}?)[\"”]|(?P<{name}u>(?:[^\"”,;.:]|[.,](?=\d)){{1,60}}?))"


_WORDS = (
    r"(?:the\s+)?(?:(?:reference|references)\s+to\s+(?:the\s+)?|words?\s+|figures?\s+|number\s+|amount\s+|sum\s+|"
    r"period\s+(?:of\s+)?|date\s+|percentage\s+|expression\s+)?"
)
_END = r"\s*(?=[.;]|$|\s+(?:and|in\s+(?:its|their)\s+place)\b)"

_RE = re.IGNORECASE | re.MULTILINE

REPLACE_RE = re.compile(
    rf"{_TARGET}\s+{_AUX}(?:deleted{_ENTIRE}\s+and\s+(?:replaced|substituted){_ENTIRE}\s+(?:with|by)"
    rf"|replaced{_ENTIRE}\s+(?:with|by)|amended\s+(?:and\s+restated\s+)?(?:to\s+read|so\s+as\s+to\s+read|so\s+that\s+it\s+reads|"
    rf"as\s+follows)|restated\s+(?:to\s+read|as\s+follows)|varied\s+(?:to\s+read|as\s+follows)|changed\s+to|"
    rf"substituted\s+(?:with|by)|read\s+as(?!\s+if)(?:\s+follows)?|reads?(?:\s+as\s+follows)?)"
    rf"(?:\s+the\s+following)?(?:\s+(?:new\s+)?(?:clause|section|paragraph)\s+[\d.]+)?\s*(?:,|:)?\s*(?:{_QUOTE}|{_FOLLOW})",
    _RE,
)
IMPERATIVE_REPLACE_RE = re.compile(
    rf"\b(?:delete|replace)\s+{_TARGET}\s+(?:and\s+(?:replace|substitute)\s+(?:it|them)\s+)?(?:with|by)"
    rf"(?:\s+the\s+following)?\s*:?\s*(?:{_QUOTE}|{_FOLLOW})",
    _RE,
)
SUBSTITUTED_FOR_RE = re.compile(
    rf"(?:the\s+following|a\s+new\s+(?:clause|section)(?:\s+[\d.]+)?)\s+{_AUX}substituted\s+for\s+{_TARGET}\s*:?\s*"
    rf"(?:{_QUOTE}|{_FOLLOW})",
    _RE,
)
# "Schedule 2 is replaced by the schedule set out in the Annex" - the new text is elsewhere in the amendment
SCHEDULE_REPLACE_RE = re.compile(
    rf"(?P<sched>{_SCHED}\s+(?:\d+|[A-Z])\b){_OF}\s+{_AUX}(?:deleted{_ENTIRE}\s+and\s+)?(?:replaced|substituted)"
    rf"{_ENTIRE}\s+(?:with|by)\s+(?P<where>[^\"“.;]{{3,160}})",
    _RE,
)
INSERT_AT_RE = re.compile(
    rf"(?:the\s+following\s+|a\s+)?(?:new\s+)?(?:clause|section|paragraph)(?:\s+(?P<sec>{_N}))?\s+{_AUX}(?:added|inserted)"
    rf"\s+(?:immediately\s+)?(?P<pos>after|before|following)\s+{_CL}\s+(?P<anchor>{_N}){_OF}"
    rf"(?:\s+as\s+(?:a\s+new\s+)?(?:clause|section|paragraph)\s+(?P<sec2>{_N}))?(?:\s*,?\s*as\s+follows)?\s*:?\s*"
    rf"(?:{_QUOTE}|{_FOLLOW})",
    _RE,
)
INSERT_IMPERATIVE_RE = re.compile(
    rf"\b(?:insert|add)\s+(?:the\s+following\s+)?(?:(?:a\s+)?new\s+)?(?:(?:clause|section|paragraph)(?:\s+(?P<sec>{_N}))?\s+)?"
    rf"(?:immediately\s+)?(?P<pos>after|before|following)\s+{_CL}\s+(?P<anchor>{_N}){_OF}\s*:?\s*(?:{_QUOTE}|{_FOLLOW})",
    _RE,
)
INSERT_AFTER_LEAD_RE = re.compile(
    rf"(?:immediately\s+)?(?P<pos>after|before|following)\s+{_CL}\s+(?P<anchor>{_N}){_OF},?\s+(?:insert|add|there\s+"
    rf"(?:is|are|shall\s+be)\s+(?:inserted|added))(?:\s+the\s+following)?(?:\s+(?:new\s+)?(?:clause|section)"
    rf"(?:\s+(?P<sec>{_N}))?)?\s*:?\s*(?:{_QUOTE}|{_FOLLOW})",
    _RE,
)
INSERT_RE = re.compile(
    rf"(?:the\s+following|a\s+new)\s+(?:new\s+)?(?:clause|section|paragraph)?\s*{_AUX}(?:added|inserted)"
    rf"(?:\s+(?:to|into)\s+(?:the\s+)?\w+)?\s+as\s+(?:a\s+new\s+)?(?:clause|section|paragraph)\s+"
    rf"(?P<sec>\d+(?:\.\d+)*)\s*:?\s*(?:{_QUOTE}|{_FOLLOW})",
    _RE,
)
INSERT_RE2 = re.compile(
    rf"(?:a\s+new\s+)?(?:clause|section)\s+(?P<sec>\d+(?:\.\d+)*)\s+{_AUX}(?:added|inserted)"
    rf"[^:\"“]{{0,60}}:?\s*(?:{_QUOTE}|{_FOLLOW})",
    _RE,
)
DELETE_RE = re.compile(
    rf"{_TARGET}\s+{_AUX}(?:deleted|removed|struck(?:\s+out)?|revoked|omitted|cancelled){_ENTIRE}"
    rf"(?!\s+and\s+(?:replaced|substituted))"
    rf"(?:\s+(?:with\s+effect\s+)?from\s+[^.;]{{1,40}})?"
    rf"(?:\s+and\s+(?:shall\s+|will\s+)?(?:have\s+no\s+further\s+effect|is\s+of\s+no\s+further\s+effect|"
    rf"shall\s+cease\s+to\s+apply|no\s+longer\s+applies))?\s*(?:[.;]|$)",
    _RE,
)
CEASE_RE = re.compile(
    rf"{_TARGET}\s+(?:shall|will|is\s+to)\s+(?:cease\s+to\s+(?:apply|have\s+effect)|no\s+longer\s+(?:apply|have\s+effect)|"
    rf"have\s+no\s+further\s+(?:force\s+or\s+)?effect)(?:\s+(?:with\s+effect\s+)?(?:from|on)\s+[^.;]{{1,40}})?\s*(?:[.;]|$)",
    _RE,
)
IMPERATIVE_DELETE_RE = re.compile(rf"\bdelete\s+{_TARGET}\s*(?:[.;]|$)", _RE)

_CHANGE = r"(?:replaced|substituted|amended|changed|deleted\s+and\s+replaced)"
MODIFY_IN_RE = re.compile(  # In clause 5.2, the words "30 days" are replaced by "45 days".
    rf"\bin\s+{_TARGET},?\s+{_WORDS}{_val('old')}\s+{_AUX}{_CHANGE}\s+(?:with|by|to)\s+(?:the\s+words\s+)?{_val('new')}{_END}",
    _RE,
)
MODIFY_BECOMES_RE = re.compile(  # In clause 5.2, "30 days" becomes "45 days".
    rf"\bin\s+{_TARGET},?\s+{_WORDS}{_val('old')}\s+(?:becomes|shall\s+become|will\s+become)\s+{_val('new')}{_END}",
    _RE,
)
MODIFY_WORDS_IN_RE = re.compile(  # The words "30 days" in clause 5.2 are replaced by "45 days".
    rf"{_WORDS}{_val('old')}\s+in\s+{_TARGET}\s+{_AUX}{_CHANGE}\s+(?:with|by|to)\s+(?:the\s+words\s+)?{_val('new')}{_END}",
    _RE,
)
MODIFY_BY_DELETING_RE = re.compile(  # Clause 5.2 is amended by deleting "30 days" and inserting "45 days".
    rf"{_TARGET}\s+{_AUX}(?:amended|varied)\s+by\s+(?:deleting|removing|striking(?:\s+out)?)\s+{_WORDS}{_val('old')}\s+"
    rf"and\s+(?:inserting|substituting|adding|replacing\s+(?:it|them)\s+with)(?:\s+in\s+(?:its|their)\s+place)?\s+"
    rf"(?:the\s+words\s+)?{_val('new')}{_END}",
    _RE,
)
MODIFY_BY_REPLACING_RE = re.compile(  # Clause 5.2 is amended by replacing "30 days" with "45 days".
    rf"{_TARGET}\s+{_AUX}(?:amended|varied)\s+by\s+(?:replacing|changing|increasing|reducing|decreasing|extending|"
    rf"shortening)\s+{_WORDS}{_val('old')}\s+(?:with|by|to)\s+(?:the\s+words\s+)?{_val('new')}{_END}",
    _RE,
)
MODIFY_SUBSTITUTING_FOR_RE = re.compile(  # Clause 3.1 is amended by substituting "£1,400" for "£1,250".
    rf"{_TARGET}\s+{_AUX}(?:amended|varied)\s+by\s+substituting\s+{_WORDS}{_val('new')}\s+for\s+{_WORDS}{_val('old')}{_END}",
    _RE,
)
MODIFY_READ_AS_IF_RE = re.compile(  # Clause 2 shall be read as if "X" were replaced by "Y" / were deleted.
    rf"{_TARGET}\s+{_AUX}(?:read|construed|interpreted)\s+as\s+if\s+{_WORDS}{_val('old')}\s+(?:were|was|had\s+been)\s+"
    rf"(?:(?:replaced|substituted)\s+(?:with|by)\s+(?:the\s+words\s+)?{_val('new')}|(?P<gone>deleted|omitted|removed))",
    _RE,
)
MODIFY_IMPERATIVE_RE = re.compile(  # In clause 5.2, delete "30 days" and insert "45 days" / replace "a" with "b".
    rf"\bin\s+{_TARGET},?\s+(?:delete\s+{_WORDS}{_val('old')}\s+and\s+(?:insert|substitute)|replace\s+{_WORDS}{_val('old2')}"
    rf"\s+with)\s+{_val('new')}{_END}",
    _RE,
)
RENUMBER_RE = re.compile(
    rf"{_CL}\s+(?P<a>{_N})(?:\s+(?P<rng>to|and|-|–)\s+(?P<b>{_N}))?{_OF}\s+{_AUX}(?:re-?numbered)\s+(?:as\s+)?"
    rf"(?:{_CL}\s+)?(?P<c>{_N})(?:\s+(?:to|and|-|–)\s+(?P<d>{_N}))?",
    _RE,
)
# Document-level: "This Agreement amends and restates the Services Agreement in its entirety"
RESTATE_RE = re.compile(
    r"\bamend(?:s|ing)\s+and\s+restat(?:es|ing)\s+(?!(?:clause|section|schedule|paragraph)s?\b)"
    r"|^\s*amended\s+and\s+restated\b|\brestates?\s+(?:the\s+[^.;]{1,80}?)?\s*in\s+(?:its|their)\s+entirety"
    r"|\bsupersedes?\s+and\s+replaces?\s+the\s+[^.;]{1,80}?\s+in\s+(?:its|their)\s+entirety",
    re.I,
)


@dataclass
class Instruction:
    target: str
    action: str  # replace | delete | insert | modify | renumber | restate
    new_text: str | None
    start: int
    end: int
    new_start: int | None = None
    new_end: int | None = None
    old_text: str | None = None
    anchor: str | None = None
    position: str | None = None
    renumber_to: str | None = None
    follows: bool = False  # replacement text is in the passage(s) that follow


def _sec(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _target(m: re.Match[str]) -> str:
    g = m.groupdict()
    if g.get("sec"):
        return _sec(g["sec"])
    if g.get("sched"):
        word, ident = g["sched"].split()
        return f"{word.title()} {ident.upper() if ident.isalpha() else ident}"
    title = g.get("title") or g.get("title2") or ""
    return "title:" + re.sub(r"\s+", " ", title).strip()


def _v(m: re.Match[str], name: str) -> str | None:
    for key in (name, name + "u", name + "2", name + "2u"):
        if key in m.groupdict() and m.group(key) is not None:
            return m.group(key).strip()
    return None


def _new(m: re.Match[str]) -> tuple[str | None, int | None, int | None, bool]:
    if m.groupdict().get("new") is not None:
        return m["new"].strip(), m.start("new"), m.end("new"), False
    return None, None, None, bool(m.groupdict().get("follows") is not None)


def _expand_range(a: str, b: str) -> list[str] | None:
    pa, pb = a.split("."), b.split(".")
    if len(pa) != len(pb) or pa[:-1] != pb[:-1] or not (pa[-1].isdigit() and pb[-1].isdigit()):
        return None
    lo, hi = int(pa[-1]), int(pb[-1])
    if hi < lo or hi - lo > 50:
        return None
    return [".".join([*pa[:-1], str(i)]) for i in range(lo, hi + 1)]


def parse_instructions(text: str) -> list[Instruction]:
    out: list[Instruction] = []
    taken: list[tuple[int, int]] = []

    def add(ins: Instruction) -> None:
        if not any(a <= ins.start < b or ins.start <= a < ins.end for a, b in taken):
            taken.append((ins.start, ins.end))
            out.append(ins)

    for rx in (INSERT_AT_RE, INSERT_IMPERATIVE_RE, INSERT_AFTER_LEAD_RE):
        for m in rx.finditer(text):
            new, ns, ne, follows = _new(m)
            anchor = _sec(m["anchor"])
            sec = m.groupdict().get("sec") or m.groupdict().get("sec2")
            if not sec and new:
                lead = re.match(r"\s*(\d+(?:\.\d+)+)\s", new)
                sec = lead.group(1) if lead else None
            pos = "before" if m["pos"].lower() == "before" else "after"
            target = _sec(sec) if sec else f"{pos} {anchor}"
            add(Instruction(target, "insert", new, m.start(), m.end(), ns, ne, anchor=anchor, position=pos, follows=follows))
    for rx in (MODIFY_READ_AS_IF_RE, MODIFY_SUBSTITUTING_FOR_RE, MODIFY_BY_DELETING_RE, MODIFY_BY_REPLACING_RE,
               MODIFY_IN_RE, MODIFY_BECOMES_RE, MODIFY_WORDS_IN_RE, MODIFY_IMPERATIVE_RE):
        for m in rx.finditer(text):
            old = _v(m, "old")
            new = "" if m.groupdict().get("gone") else _v(m, "new")
            if not old or new is None:
                continue
            add(Instruction(_target(m), "modify", new, m.start(), m.end(), old_text=old))
    for rx in (REPLACE_RE, IMPERATIVE_REPLACE_RE, SUBSTITUTED_FOR_RE):
        for m in rx.finditer(text):
            new, ns, ne, follows = _new(m)
            add(Instruction(_target(m), "replace", new, m.start(), m.end(), ns, ne, follows=follows))
    for m in SCHEDULE_REPLACE_RE.finditer(text):
        add(Instruction(_target(m), "replace", None, m.start(), m.end(), follows=True))
    for rx in (INSERT_RE, INSERT_RE2):
        for m in rx.finditer(text):
            new, ns, ne, follows = _new(m)
            add(Instruction(_sec(m["sec"]), "insert", new, m.start(), m.end(), ns, ne, follows=follows))
    for m in RENUMBER_RE.finditer(text):
        a, b, c, d = (_sec(x) if x else None for x in (m["a"], m["b"], m["c"], m["d"]))
        pairs: list[tuple[str, str]] = []
        if b and d and (m["rng"] or "").lower() == "and":
            pairs = [(a, c), (b, d)]  # type: ignore[list-item]
        elif b and d:
            src, dst = _expand_range(a, b), _expand_range(c, d)  # type: ignore[arg-type]
            if src and dst and len(src) == len(dst):
                pairs = list(zip(src, dst, strict=True))
        elif not b and not d:
            pairs = [(a, c)]  # type: ignore[list-item]
        if not pairs:
            continue
        first = True
        for old, new_num in pairs:
            ins = Instruction(old, "renumber", None, m.start(), m.end(), renumber_to=new_num)
            if first:
                add(ins)
                first = False
            elif out and out[-1].start == m.start():
                out.append(ins)  # same sentence, several renumberings
    for rx in (DELETE_RE, CEASE_RE, IMPERATIVE_DELETE_RE):
        for m in rx.finditer(text):
            add(Instruction(_target(m), "delete", None, m.start(), m.end()))
    return sorted(out, key=lambda i: i.start)


def find_restatement(text: str) -> re.Match[str] | None:
    """A document-level "amends and restates ... in its entirety" statement, or None."""
    return RESTATE_RE.search(text)


# ------------------------------------------------------------------ numbers in amended wording
_WORD_NUM = (
    r"(?:(?:" + "|".join(w for w in sorted({w.split("-")[0] for w in NUMBER_WORDS if "-" in w}, key=len, reverse=True))
    + r")(?:[-\s](?:one|two|three|four|five|six|seven|eight|nine))?|"
    + "|".join(sorted((w for w in NUMBER_WORDS if "-" not in w), key=len, reverse=True))
    + r")"
)
_NUM_TOKEN = re.compile(
    rf"\b(?P<w>{_WORD_NUM})\s*\(\s*(?P<d1>\d+)\s*\)|(?P<d2>\d+(?:[.,]\d+)*)|\b(?P<w2>{_WORD_NUM})\b", re.I
)


def _word_value(w: str) -> int | None:
    return NUMBER_WORDS.get(re.sub(r"[\s-]+", "-", w.lower()))


def _number_alternatives(value: int) -> str:
    digits = rf"(?<![\d.,]){value}(?![\d]|[.,]\d)"
    words = number_words(value)
    if words is None:
        return digits
    w = r"[\s-]".join(re.escape(part) for part in words.split("-"))
    return rf"(?:\b{w}\s*\(\s*{value}\s*\)|\b{w}\b|{digits})"


def number_tolerant_pattern(phrase: str) -> str:
    """Regex for `phrase` that also matches numbers written as words, digits, or "thirty (30)"."""
    parts: list[str] = []
    pos = 0
    for m in _NUM_TOKEN.finditer(phrase):
        parts.append(_literal(phrase[pos : m.start()]))
        value: int | None
        if m["d1"]:
            value = int(m["d1"])
        elif m["d2"]:
            value = int(m["d2"]) if m["d2"].isdigit() else None
        else:
            value = _word_value(m["w2"])
        if value is None:
            parts.append(_literal(m.group(0)))
        else:
            parts.append(_number_alternatives(value))
        pos = m.end()
    parts.append(_literal(phrase[pos:]))
    return "".join(parts)


def _literal(s: str) -> str:
    return r"\s+".join(re.escape(p) for p in s.split(" ")) if s.strip() else (r"\s*" if s else "")
