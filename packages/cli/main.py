"""`claimtrace` command line: serve, ingest, analyze, ask, verify, report, eval."""

from __future__ import annotations

import argparse
import json
import sys


def _store(db: str | None):  # type: ignore[no-untyped-def]
    from pathlib import Path

    from claimtrace.core.config import Settings
    from claimtrace.core.store import Store

    path = db or Settings().db_path
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    return Store(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="claimtrace", description="ClaimTrace: commitments, grounded Q&A, verification. "
                                                                "Not legal advice.")
    ap.add_argument("--db", help="SQLite path (default: $CLAIMTRACE_DB or ./data/claimtrace.db)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sv = sub.add_parser("serve", help="run the API and web UI")
    sv.add_argument("--host")
    sv.add_argument("--port", type=int)
    ing = sub.add_parser("ingest", help="add a document and analyse it")
    ing.add_argument("path")
    ing.add_argument("--title")
    ing.add_argument("--type", dest="doc_type")
    ing.add_argument("--amends", help="document id this document amends")
    sub.add_parser("list", help="list documents")
    a = sub.add_parser("ask", help="ask a grounded question")
    a.add_argument("question")
    a.add_argument("--doc", action="append", dest="docs")
    v = sub.add_parser("verify", help="compare two documents")
    v.add_argument("base")
    v.add_argument("other")
    r = sub.add_parser("report", help="export a report")
    r.add_argument("doc")
    r.add_argument("--format", choices=["md", "json", "html", "ics"], default="md")
    d = sub.add_parser("delete", help="delete a document and everything derived from it")
    d.add_argument("doc")
    ev = sub.add_parser("eval", help="evaluation suite")
    evs = ev.add_subparsers(dest="eval_cmd", required=True)
    er = evs.add_parser("run")
    er.add_argument("--suite", default="core")
    er.add_argument("--model", default="rules", help="rules | keyword | openai:<model> | ollama:<model>")
    er.add_argument("--out", default="evals/runs")
    er.add_argument("--repeats", type=int, default=1)
    ep = evs.add_parser("report")
    ep.add_argument("--run", help="run directory (default: latest)")
    ep.add_argument("--format", choices=["markdown", "json"], default="markdown")
    ep.add_argument("--out-dir", default="evals/runs")
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        from claimtrace.api.main import create_app
        from claimtrace.core.config import Settings

        s = Settings()
        if args.host:
            s.host = args.host
        if args.port:
            s.port = args.port
        if args.db:
            s.db_path = args.db
        print(f"ClaimTrace on http://{s.host}:{s.port}  (API docs: /docs). Not legal advice.", file=sys.stderr)
        uvicorn.run(create_app(s), host=s.host, port=s.port, log_level="warning", server_header=False)
        return 0
    if args.cmd == "eval":
        from claimtrace.evaluation.runner import report_cmd, run_cmd

        if args.eval_cmd == "run":
            return run_cmd(args.suite, args.model, args.out, args.repeats)
        return report_cmd(args.run, args.format, args.out_dir)

    store = _store(args.db)
    if args.cmd == "ingest":
        from claimtrace.extraction import analyze_document, apply_amendments
        from claimtrace.ingestion import IngestOptions, ingest_file

        doc = ingest_file(store, args.path, IngestOptions(title=args.title, doc_type=args.doc_type,
                                                          amends_document_id=args.amends))
        apply_amendments(store)
        run = analyze_document(store, doc.id)
        print(json.dumps({"document_id": doc.id, "title": doc.title, "type": doc.doc_type.value,
                          "warnings": doc.warnings, "run": run.status, "counts": run.counts}, indent=2))
    elif args.cmd == "list":
        for doc in store.list_documents():
            print(f"{doc.id}  {doc.doc_type.value:12} {doc.version_label:6} {doc.status:9} {doc.title}")
    elif args.cmd == "ask":
        from claimtrace.verification import answer_question

        ans = answer_question(store, args.question, args.docs)
        print(f"[{ans.status.value} · confidence {ans.confidence.value}]\n{ans.answer_text}\n")
        for c in ans.citations:
            print(f"  {c.role}: \"{c.span.quote}\" — {c.span.document_title} §{c.span.section or '?'}")
        for cv in ans.caveats:
            print(f"  note: {cv}")
    elif args.cmd == "verify":
        from claimtrace.verification import verify_documents

        run = verify_documents(store, args.base, args.other)
        print(f"mode: {run.mode}  summary: {run.summary}")
        for f in run.findings:
            if f.verdict.value != "not_addressed" or run.mode != "amendment":
                print(f"- [{f.verdict.value} · {f.severity.value}] {f.subject_text[:90]}\n    {f.explanation}")
    elif args.cmd == "report":
        from claimtrace.verification.report import build_report, deadlines_ics, render_html, render_markdown

        if args.format == "ics":
            sys.stdout.write(deadlines_ics(store, args.doc))
            return 0
        rep = build_report(store, args.doc)
        out = {"md": render_markdown, "html": render_html}.get(args.format)
        print(out(rep) if out else json.dumps(rep, indent=2, default=str))
    elif args.cmd == "delete":
        from claimtrace.extraction import apply_amendments

        print(json.dumps(store.delete_document(args.doc)))
        apply_amendments(store)
    return 0


if __name__ == "__main__":
    sys.exit(main())
