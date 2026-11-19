#!/usr/bin/env python3
"""ClaimTrace skill runner: one entry point that prints JSON.

    claimtrace_run.py analyze <files or folders...>
    claimtrace_run.py ask "<question>" <files or folders...>
    claimtrace_run.py verify <base file> <other file>
    claimtrace_run.py doctor

Everything runs in this process, in memory (SQLite ":memory:"). Nothing is written to disk and nothing is
sent over the network: the engine is the rules engine, no language model is configured.

Which engine runs (--engine, or $CLAIMTRACE_ENGINE; default auto):
  installed  the `claimtrace` package that a locally installed `claimtrace` command runs with
  bundled    the copy of the engine shipped in ../vendor (built by scripts/build_skill_zip.py),
             or, in a source checkout of the ClaimTrace repository, its packages/ directory
  auto       installed if a `claimtrace` command is on PATH and works, otherwise bundled

ClaimTrace is a document-review aid, not legal advice.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

RUNNER_VERSION = "0.3.0"
SKILL_DIR = Path(__file__).resolve().parent.parent
VENDOR = SKILL_DIR / "vendor"
SUPPORTED = (".pdf", ".docx", ".md", ".markdown", ".txt", ".text")
AMENDMENT_ACCURACY = "0.60 (95% interval 0.51-0.70, n=105, wording the engine had not seen)"
NOTICE = {
    "not_legal_advice": "ClaimTrace is a document-review aid. It is not legal advice and does not decide what is true "
                        "or legally binding.",
    "amendment_results": "Amendment results (what an amendment changed, replaced or deleted) need a human check: on "
                         f"amendment wording it had not seen before, the engine's verdict accuracy is {AMENDMENT_ACCURACY}.",
    "quotes": "Every quote below was re-checked against the stored document text (quote_verified). Items whose quote "
              "could not be re-checked are left out and counted in dropped_unverified.",
}
EXIT_USAGE, EXIT_DEPENDENCY, EXIT_INPUT = 2, 3, 4


class RunnerError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = EXIT_INPUT) -> None:
        super().__init__(message)
        self.code, self.message, self.exit_code = code, message, exit_code


# ---------------------------------------------------------------------------------------------- engine

def _installed_python() -> str | None:
    """The interpreter that a `claimtrace` command on PATH runs with, if that command works."""
    exe = shutil.which("claimtrace")
    if not exe:
        return None
    try:
        subprocess.run([exe, "--help"], capture_output=True, timeout=30, check=True)  # noqa: S603
        with open(exe, "rb") as fh:
            first = fh.readline().decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not first.startswith("#!"):
        return None
    parts = first[2:].split()
    if not parts:
        return None
    py = parts[1] if Path(parts[0]).name == "env" and len(parts) > 1 else parts[0]
    try:
        probe = subprocess.run([py, "-c", "import claimtrace; print(claimtrace.__version__)"],  # noqa: S603
                               capture_output=True, timeout=30, check=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return py if probe.stdout.strip() else None


def _source_checkout() -> Path | None:
    """packages/ of a ClaimTrace source checkout this script lives in (developers using --plugin-dir)."""
    for parent in SKILL_DIR.parents:
        pyproject = parent / "pyproject.toml"
        if (parent / "packages" / "__init__.py").is_file() and pyproject.is_file():
            if 'name = "claimtrace"' in pyproject.read_text(encoding="utf-8", errors="replace"):
                return parent / "packages"
    return None


def _stub_httpx() -> None:
    """claimtrace.integrations imports httpx at module level for the optional LLM adapter. This runner never
    configures a model, so where httpx is not installed a stub stands in; any use of it fails loudly."""
    if importlib.util.find_spec("httpx") is not None:
        return
    mod = types.ModuleType("httpx")

    class HTTPError(Exception):
        pass

    class BaseTransport:
        pass

    class Client:
        def __init__(self, *a: object, **k: object) -> None:
            raise RuntimeError("network access is disabled in the ClaimTrace skill runner")

    mod.HTTPError, mod.BaseTransport, mod.Client = HTTPError, BaseTransport, Client  # type: ignore[attr-defined]
    mod.__claimtrace_stub__ = True  # type: ignore[attr-defined]
    sys.modules["httpx"] = mod


def check_dependencies(files: list[Path] | None = None) -> list[str]:
    """Problems that stop the engine from running here, as plain sentences (empty when all is well)."""
    problems: list[str] = []
    if sys.version_info < (3, 11):  # noqa: UP036 - the runner may be started by an older Python
        problems.append(f"Python 3.11 or newer is needed; this is Python {sys.version.split()[0]}.")
    if importlib.util.find_spec("pydantic_core") is None or importlib.util.find_spec("pydantic") is None:
        problems.append("The Python package 'pydantic' (version 2, with 'pydantic_core') is not installed. It is "
                        "compiled, so it is not bundled with this skill. Install it with: pip install 'pydantic>=2.6'")
    else:
        try:
            import pydantic

            if not pydantic.VERSION.startswith("2."):
                problems.append(f"pydantic version 2 is needed; found {pydantic.VERSION}.")
        except Exception as e:  # noqa: BLE001 - report, never crash the check
            problems.append(f"pydantic is installed but could not be imported ({type(e).__name__}).")
    if files and any(f.suffix.lower() == ".docx" for f in files) and importlib.util.find_spec("lxml") is None:
        problems.append("Reading .docx files needs the Python package 'lxml' (compiled, not bundled). Install it with: "
                        "pip install lxml. PDF, Markdown and text files work without it.")
    return problems


def load_engine(mode: str) -> dict:
    """Make `import claimtrace` work for the chosen engine. Returns {source, version, in_process_parse}."""
    if mode == "installed":
        if importlib.util.find_spec("claimtrace") is None:
            raise RunnerError("engine_not_found", "No installed claimtrace package is importable by this Python.",
                              EXIT_DEPENDENCY)
        source = "installed"
    elif (VENDOR / "src" / "claimtrace" / "__init__.py").is_file():
        sys.path.insert(0, str(VENDOR / "src"))
        # pure-Python dependency wheels go LAST, so packages already installed in the sandbox win
        for whl in sorted((VENDOR / "wheels").glob("*.whl")):
            sys.path.append(str(whl))
        source = "bundled"
    elif (pkgs := _source_checkout()) is not None:
        spec = importlib.util.spec_from_file_location("claimtrace", pkgs / "__init__.py",
                                                      submodule_search_locations=[str(pkgs)])
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules["claimtrace"] = module
        spec.loader.exec_module(module)
        source = "source-checkout"
    else:
        raise RunnerError(
            "engine_not_found",
            "The ClaimTrace engine was not found next to this script (vendor/ is missing). Use the skill zip from "
            "the GitHub release, or install ClaimTrace: pipx install 'git+https://github.com/glowstonesq1/claimtrace'",
            EXIT_DEPENDENCY,
        )
    _stub_httpx()
    import claimtrace

    # the parsing sandbox starts `python -I -m claimtrace.ingestion.worker`, which only finds an installed package
    return {"source": source, "version": claimtrace.__version__, "runner": RUNNER_VERSION,
            "in_process_parse": source != "installed"}


# ---------------------------------------------------------------------------------------------- inputs

def expand(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            out += sorted(f for f in p.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED
                          and not f.name.startswith("."))
        elif p.is_file():
            out.append(p)
        else:
            raise RunnerError("file_not_found", f"File not found: {raw}")
    seen: set[Path] = set()
    unique = [f for f in out if not (f.resolve() in seen or seen.add(f.resolve()))]  # type: ignore[func-returns-value]
    if not unique:
        raise RunnerError("no_files", "No supported files (PDF, DOCX, Markdown, plain text) were given.")
    return unique


class Session:
    """All documents of one run, ingested and analysed in an in-memory store."""

    def __init__(self, files: list[Path], engine: dict) -> None:
        from claimtrace.core.store import Store
        from claimtrace.extraction import analyze_document, apply_amendments
        from claimtrace.ingestion import IngestError, IngestOptions, ingest_bytes

        self.store = Store(":memory:")
        self.docs = []
        self.skipped: list[dict] = []
        self.file_of: dict[str, str] = {}
        for f in files:
            try:
                data = f.read_bytes()
                doc = ingest_bytes(self.store, f.name, data, IngestOptions(sandbox=not engine["in_process_parse"]))
            except IngestError as e:
                self.skipped.append({"file": f.name, "code": e.code, "message": e.message})
                continue
            if doc.id not in self.file_of:
                self.docs.append(doc)
                self.file_of[doc.id] = f.name
        self._link_amendments()
        apply_amendments(self.store)
        for doc in self.docs:
            analyze_document(self.store, doc.id)
        self.docs = [self.store.get_document(d.id) for d in self.docs]

    def _link_amendments(self) -> None:
        """Ingestion links `amends: <title>` only to a document uploaded before it. Files come in any order here,
        so link the rest by the same rule (exact title, case-insensitive) once all are in."""
        import re

        pat = re.compile(r"^This document says it amends '(.+)', which has not been uploaded yet\.$")
        by_title = {d.title.strip().lower(): d for d in self.docs}
        for d in self.docs:
            if d.amends_document_id:
                continue
            for w in d.warnings:
                m = pat.match(w)
                target = by_title.get(m.group(1).strip().lower()) if m else None
                if target and target.id != d.id:
                    d.amends_document_id = target.id
                    d.warnings = [x for x in d.warnings if x != w]
                    self.store.update_document(d)
                    break

    # ---- helpers
    def span_ok(self, span) -> bool:  # type: ignore[no-untyped-def]
        if span is None:
            return False
        text = self.store.get_document_text(span.document_id)
        return text[span.char_start:span.char_end] == span.quote

    def quote(self, span) -> dict:  # type: ignore[no-untyped-def]
        return {"quote": span.quote, "document": span.document_title, "file": self.file_of.get(span.document_id),
                "version": span.document_version, "section": span.section, "page": span.page,
                "locator": span.locator, "char_start": span.char_start, "char_end": span.char_end,
                "quote_verified": self.span_ok(span)}

    def documents(self) -> list[dict]:
        titles = {d.id: d.title for d in self.docs}
        return [{"id": d.id, "file": self.file_of[d.id], "title": d.title, "type": d.doc_type.value,
                 "version": d.version_label, "amends": titles.get(d.amends_document_id) if d.amends_document_id else None,
                 "warnings": d.warnings} for d in self.docs]


# ---------------------------------------------------------------------------------------------- commands

def _deadline(c) -> dict | None:  # type: ignore[no-untyped-def]
    if not c.deadline or c.deadline.kind == "none":
        return None
    d = c.deadline
    return {"kind": d.kind, "text": d.raw, "date": d.date.isoformat() if d.date else None,
            "offset_days": d.offset_days, "business_days": d.business_days, "from": d.anchor,
            "ambiguous_format": d.ambiguous_format}


def register(s: Session) -> tuple[list[dict], int]:
    from claimtrace.core.models import Commitment

    rows, dropped = [], 0
    order = {d.id: i for i, d in enumerate(s.docs)}
    for doc in s.docs:
        for c in s.store.objects(Commitment, doc.id):
            if c.id.startswith("cmt_d_"):  # derived records from amendment application; the source rows cover them
                continue
            if not s.span_ok(c.provenance.span):
                dropped += 1
                continue
            rows.append({
                "id": c.id, "who": c.obliging_party, "owes": c.action, "to": c.beneficiary_party,
                "by": _deadline(c), "type": c.type.value, "modality": c.modality.value,
                "conditions": c.conditions, "exceptions": c.exceptions,
                "current": c.document_effect.value == "in_force", "effect": c.document_effect.value,
                "status": c.status.value, "confidence": c.confidence.value,
                "needs_review": c.needs_review, "review_reasons": c.review_reasons, "caveats": c.caveats,
                "from_amendment": bool(doc.amends_document_id),
                **s.quote(c.provenance.span),
            })
    rows.sort(key=lambda r: (order.get(next((d.id for d in s.docs if d.title == r["document"]), ""), 0),
                             r["char_start"]))
    return rows, dropped


def _finding(s: Session, f, mode: str) -> dict | None:  # type: ignore[no-untyped-def]
    spans = [f.subject_span, *f.supporting, *f.conflicting]
    if any(sp is not None and not s.span_ok(sp) for sp in spans):
        return None
    return {
        "verdict": f.verdict.value, "severity": f.severity.value, "mode": mode,
        "subject": s.quote(f.subject_span) if f.subject_span else {"quote": f.subject_text, "quote_verified": False},
        "supporting": [s.quote(sp) for sp in f.supporting], "conflicting": [s.quote(sp) for sp in f.conflicting],
        "explanation": f.explanation, "recommended_action": f.recommended_action, "sufficiency": f.sufficiency,
        "needs_human_check": mode == "amendment" or f.verdict.value != "consistent",
        **({"accuracy_note": NOTICE["amendment_results"]} if mode == "amendment" else {}),
    }


def verify_pair(s: Session, base_id: str, other_id: str) -> dict:
    from claimtrace.verification import verify_documents

    run = verify_documents(s.store, base_id, other_id)
    titles = {d.id: d.title for d in s.docs}
    out, dropped, not_addressed = [], 0, 0
    for f in run.findings:
        if f.verdict.value == "not_addressed":
            not_addressed += 1
            continue
        item = _finding(s, f, run.mode)
        if item is None:
            dropped += 1
        else:
            out.append(item)
    rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
    out.sort(key=lambda x: rank.get(x["severity"], 9))
    return {"mode": run.mode, "base": titles.get(run.base_document_id), "other": titles.get(run.other_document_id),
            "summary": run.summary, "findings": out, "not_addressed": not_addressed,
            "not_addressed_note": "Commitments with no matching text in the other document. This does not mean "
                                  "they were missed.",
            "dropped_unverified": dropped,
            "needs_human_check": run.mode == "amendment"}


def cross_document(s: Session) -> list[dict]:
    """The pairs a reader would check: each amendment against what it amends, each evidence or audit document
    against each contract-like document."""
    from claimtrace.core.models import EVIDENCE_TYPES, DocType

    pairs: list[tuple[str, str]] = []
    bases = [d for d in s.docs if d.doc_type not in EVIDENCE_TYPES and d.doc_type != DocType.amendment
             and not d.amends_document_id]
    for d in s.docs:
        if d.amends_document_id:
            pairs.append((d.amends_document_id, d.id))
        elif d.doc_type in EVIDENCE_TYPES:
            pairs += [(b.id, d.id) for b in bases]
    return [verify_pair(s, a, b) for a, b in pairs]


def answer(s: Session, question: str) -> dict:
    from claimtrace.verification import NOT_FOUND, answer_question

    ans = answer_question(s.store, question)
    cites, dropped = [], 0
    for c in ans.citations:
        if c.verified and s.span_ok(c.span):
            cites.append({"role": c.role, "note": c.note, **s.quote(c.span)})
        else:
            dropped += 1
    supported = any(c["role"] == "supports" for c in cites)
    not_found = ans.answer_text.startswith(NOT_FOUND) or not cites
    return {"question": ans.question, "status": ans.status.value, "confidence": ans.confidence.value,
            "found": not not_found, "has_supporting_quote": supported,
            "answer": NOT_FOUND if not_found and not cites else ans.answer_text,
            "not_found_sentence": NOT_FOUND,
            "citations": cites, "caveats": ans.caveats, "follow_ups": ans.follow_ups,
            "needs_review": ans.needs_review, "dropped_unverified": dropped}


def _resolve(s: Session, f: Path) -> str:
    for d in s.docs:
        if s.file_of[d.id] == f.name:
            return d.id
    raise RunnerError("not_ingested", f"{f.name} could not be read: " +
                      "; ".join(x["message"] for x in s.skipped if x["file"] == f.name))



def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="claimtrace_run.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["auto", "installed", "bundled"],
                    default=os.environ.get("CLAIMTRACE_ENGINE", "auto"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="register of commitments plus cross-document findings")
    a.add_argument("paths", nargs="+")
    q = sub.add_parser("ask", help="answer a question with verified quotes")
    q.add_argument("question")
    q.add_argument("paths", nargs="+")
    v = sub.add_parser("verify", help="compare two documents")
    v.add_argument("base")
    v.add_argument("other")
    sub.add_parser("doctor", help="report which engine would run and whether its dependencies are present")
    return ap


def run(args: argparse.Namespace) -> dict:
    if args.cmd == "doctor":
        problems = check_dependencies()
        engine = None
        if not problems:
            try:
                engine = load_engine(args.engine)
            except RunnerError as e:
                problems.append(e.message)
        return {"ok": not problems, "command": "doctor", "python": sys.version.split()[0], "engine": engine,
                "installed_cli_python": _installed_python(), "problems": problems}
    files = expand(args.paths if args.cmd in ("analyze", "ask") else [args.base, args.other])
    if args.cmd == "verify" and len(files) != 2:
        raise RunnerError("usage", "verify needs two different files.", EXIT_USAGE)
    problems = check_dependencies(files)
    if problems:
        raise RunnerError("missing_dependency", " ".join(problems), EXIT_DEPENDENCY)
    engine = load_engine(args.engine)
    s = Session(files, engine)
    out: dict = {"ok": True, "command": args.cmd, "tool": "ClaimTrace", "engine": engine, "notice": NOTICE,
                 "documents": s.documents(), "skipped_files": s.skipped}
    if args.cmd == "analyze":
        rows, dropped = register(s)
        out["register"] = rows
        out["register_dropped_unverified"] = dropped
        out["cross_document"] = cross_document(s)
    elif args.cmd == "ask":
        out["answer"] = answer(s, args.question)
    else:
        out["verification"] = verify_pair(s, _resolve(s, files[0]), _resolve(s, files[1]))
    return out


def _strip_engine(argv: list[str]) -> list[str]:
    out, skip = [], False
    for x in argv:
        if skip:
            skip = False
        elif x == "--engine":
            skip = True
        elif not x.startswith("--engine="):
            out.append(x)
    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parser().parse_args(argv)
        if args.engine == "auto":
            py = None if args.cmd == "doctor" or os.environ.get("CLAIMTRACE_RUNNER_CHILD") else _installed_python()
            if py:  # re-run with the installed engine's interpreter, where its parser sandbox also works
                env = {**os.environ, "CLAIMTRACE_RUNNER_CHILD": "1"}
                cmd = [py, str(Path(__file__).resolve()), "--engine", "installed", *_strip_engine(argv)]
                return subprocess.run(cmd, env=env, check=False).returncode  # noqa: S603
            args.engine = "bundled"
        out, code = run(args), 0
    except RunnerError as e:
        out, code = {"ok": False, "error": e.code, "message": e.message}, e.exit_code
        print(f"claimtrace_run: {e.message}", file=sys.stderr)
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
