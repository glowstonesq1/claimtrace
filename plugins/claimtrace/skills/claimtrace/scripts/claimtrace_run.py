#!/usr/bin/env python3
"""ClaimTrace skill runner: one entry point that prints JSON.

    claimtrace_run.py analyze <files or folders...>
    claimtrace_run.py ask --question-file - <files or folders...>  <<'CLAIMTRACE_QUESTION'
    <question>
    CLAIMTRACE_QUESTION
    claimtrace_run.py ask '<question>' <files or folders...>   (the question as an argument also works)
    claimtrace_run.py verify <base file> <other file>
    claimtrace_run.py doctor
    claimtrace_run.py install --yes [--dry-run]

Analysis runs in memory (SQLite ":memory:"). Nothing is written to disk and nothing is sent over the network:
the engine is the rules engine, no language model is configured. The only command that uses the network is
`install`, and it does nothing without --yes, which Claude passes only after the user agreed.

Which engine runs (--engine, or $CLAIMTRACE_ENGINE; default auto, see choose_engine):
  1. a working `claimtrace` command on PATH (its Python is used)
  2. the private engine `install --yes` put in the plugin's data dir (ClaimTrace INSTALL_TAG, pinned)
  3. the copy bundled in ../vendor (built by scripts/build_skill_zip.py; present in the release zips)
  4. packages/ of a ClaimTrace source checkout this script lives in
  5. none: exit 5, "needs_install" (nothing is installed automatically)

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
EXIT_USAGE, EXIT_DEPENDENCY, EXIT_INPUT, EXIT_NEEDS_INSTALL = 2, 3, 4, 5
# The release a plugin installed from the marketplace may install, with the user's permission (see `install`).
INSTALL_TAG = "v0.3.0"
INSTALL_SPEC = f"claimtrace @ git+https://github.com/glowstonesq1/claimtrace@{INSTALL_TAG}"


class RunnerError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = EXIT_INPUT, extra: dict | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.exit_code, self.extra = code, message, exit_code, extra or {}


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
    return py if _has_claimtrace(py) else None


def _has_claimtrace(py: str) -> bool:
    try:
        probe = subprocess.run([py, "-c", "import claimtrace; print(claimtrace.__version__)"],  # noqa: S603
                               capture_output=True, timeout=30, check=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(probe.stdout.strip())


def data_dir() -> Path:
    """Where the plugin may keep a private engine: Claude Code's per-plugin data dir if it gives one."""
    for var in ("CLAIMTRACE_PLUGIN_DATA", "CLAUDE_PLUGIN_DATA"):
        if os.environ.get(var):
            return Path(os.environ[var])
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "claimtrace-claude-plugin"


def engine_venv() -> Path:
    return data_dir() / f"engine-{INSTALL_TAG}"


def _venv_bin(venv_dir: Path, name: str) -> Path:
    return venv_dir / ("Scripts" if os.name == "nt" else "bin") / (name + (".exe" if os.name == "nt" else ""))


def _venv_python() -> str | None:
    """The private engine installed earlier with `install --yes`, if it is there and works."""
    py = _venv_bin(engine_venv(), "python")
    return str(py) if py.is_file() and _has_claimtrace(str(py)) else None


def choose_engine(cli_python: str | None, venv_python: str | None, has_vendor: bool, checkout: bool) -> tuple[str, str | None]:
    """The auto-mode decision, kept pure for tests: (source, python to re-run with or None).

    installed CLI > private engine installed with the user's permission > bundled copy > source checkout >
    none ("needs_install": the runner installs nothing itself; Claude must ask the user first)."""
    if cli_python:
        return "installed", cli_python
    if venv_python:
        return "plugin-venv", venv_python
    if has_vendor:
        return "bundled", None
    if checkout:
        return "source-checkout", None
    return "needs_install", None


def install_plan(venv_dir: Path) -> list[list[str]]:
    py = str(_venv_bin(venv_dir, "python"))
    return [[sys.executable, "-m", "venv", "--clear", str(venv_dir)],
            [py, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", INSTALL_SPEC]]


def install(yes: bool, dry_run: bool) -> dict:
    """Install the pinned release into the private venv. Only with --yes, which Claude passes only after the user
    agreed in the conversation."""
    venv_dir = engine_venv()
    plan = install_plan(venv_dir)
    out = {"command": "install", "spec": INSTALL_SPEC, "venv": str(venv_dir), "steps": [" ".join(c) for c in plan]}
    if not yes:
        raise RunnerError("consent_required", "Nothing was installed. Ask the user first; run `install --yes` only "
                          f"after they agree. It would install {INSTALL_SPEC} into {venv_dir}.", EXIT_USAGE)
    if dry_run:
        return {"ok": True, "dry_run": True, **out}
    if sys.version_info < (3, 11):  # noqa: UP036
        raise RunnerError("python_too_old", "Installing the engine needs Python 3.11 or newer.", EXIT_DEPENDENCY)
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    for cmd in plan:
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
        if r.returncode != 0:
            tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
            raise RunnerError("install_failed", f"Step failed: {' '.join(cmd)}: " + " / ".join(tail), EXIT_DEPENDENCY)
    if not _has_claimtrace(plan[1][0]):
        raise RunnerError("install_failed", "The engine was installed but cannot be imported.", EXIT_DEPENDENCY)
    return {"ok": True, **out}


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
        source = os.environ.get("CLAIMTRACE_ENGINE_SOURCE", "installed")
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
            "in_process_parse": source in ("bundled", "source-checkout")}


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
    q.add_argument("--question-file", metavar="FILE",
                   help="read the question from FILE ('-' for stdin), so the shell never sees its text; then every "
                        "positional argument is a document")
    q.add_argument("words", nargs="+", metavar="[question] paths")
    v = sub.add_parser("verify", help="compare two documents")
    v.add_argument("base")
    v.add_argument("other")
    sub.add_parser("doctor", help="report which engine would run and whether its dependencies are present")
    ins = sub.add_parser("install", help=f"install ClaimTrace {INSTALL_TAG} into a private venv (only with --yes, "
                                         "after the user agreed)")
    ins.add_argument("--yes", action="store_true", help="the user has agreed to this install")
    ins.add_argument("--dry-run", action="store_true", help="show the steps, install nothing")
    return ap


def ask_arguments(question_file: str | None, words: list[str]) -> tuple[str, list[str]]:
    """(question, paths). With --question-file the question is read verbatim (one trailing newline, as a heredoc
    adds, is dropped) and every positional is a path; otherwise the first positional is the question."""
    if question_file is None:
        if len(words) < 2:
            raise RunnerError("usage", "ask needs a question and at least one file or folder.", EXIT_USAGE)
        return words[0], words[1:]
    try:
        if question_file == "-":
            text = sys.stdin.buffer.read().decode("utf-8")
        else:
            text = Path(question_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise RunnerError("usage", f"The question could not be read ({type(e).__name__}).", EXIT_USAGE) from e
    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    if not text.strip():
        raise RunnerError("usage", "The question is empty.", EXIT_USAGE)
    return text, list(words)


def needs_install_error() -> RunnerError:
    venv_dir = engine_venv()
    return RunnerError(
        "engine_not_installed",
        "The ClaimTrace engine is not installed here and no bundled copy is present. Nothing was installed. Ask the "
        f"user once whether to install ClaimTrace {INSTALL_TAG} from GitHub into a private folder ({venv_dir}); "
        "it needs network access and about 50 MB. Only if they agree, run this script with `install --yes`, then "
        "run the original command again. Otherwise suggest the local app or the browser Try it page.",
        EXIT_NEEDS_INSTALL,
        {"needs_install": True, "install": {"tag": INSTALL_TAG, "spec": INSTALL_SPEC, "venv": str(venv_dir),
                                            "command": f"python3 {Path(__file__).resolve()} install --yes",
                                            "steps": [" ".join(c) for c in install_plan(venv_dir)]}},
    )


def auto_decision() -> tuple[str, str | None]:
    return choose_engine(_installed_python(), _venv_python(),
                         (VENDOR / "src" / "claimtrace" / "__init__.py").is_file(), _source_checkout() is not None)


def run(args: argparse.Namespace) -> dict:
    if args.cmd == "install":
        return install(args.yes, args.dry_run)
    if args.cmd == "doctor":
        problems = check_dependencies()
        decision, _ = auto_decision() if args.engine == "auto" else (args.engine, None)
        engine = None
        if not problems and decision in ("bundled", "source-checkout", "installed"):
            try:
                engine = load_engine("bundled" if decision == "source-checkout" else decision)
            except RunnerError as e:
                problems.append(e.message)
        return {"ok": not problems and decision != "needs_install", "command": "doctor",
                "python": sys.version.split()[0], "decision": decision, "engine": engine,
                "installed_cli_python": _installed_python(), "plugin_venv": str(engine_venv()), "problems": problems}
    if args.cmd == "ask":
        args.question, args.paths = ask_arguments(args.question_file, args.words)
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
        if args.engine == "auto" and args.cmd not in ("doctor", "install"):
            if os.environ.get("CLAIMTRACE_RUNNER_CHILD"):
                decision, py = "bundled", None
            else:
                decision, py = auto_decision()
            if py:  # re-run with that engine's interpreter, where its parser sandbox also works
                env = {**os.environ, "CLAIMTRACE_RUNNER_CHILD": "1", "CLAIMTRACE_ENGINE_SOURCE": decision}
                cmd = [py, str(Path(__file__).resolve()), "--engine", "installed", *_strip_engine(argv)]
                return subprocess.run(cmd, env=env, check=False).returncode  # noqa: S603
            if decision == "needs_install":
                raise needs_install_error()
            args.engine = "bundled"
        out, code = run(args), 0
    except RunnerError as e:
        out, code = {"ok": False, "error": e.code, "message": e.message, **e.extra}, e.exit_code
        print(f"claimtrace_run: {e.message}", file=sys.stderr)
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
