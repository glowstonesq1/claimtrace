---
description: Check a folder of contracts, amendments, audit reports or delivery records with ClaimTrace (register, cross-document findings, verified quotes)
argument-hint: <folder or files>
allowed-tools: Bash(python3 *claimtrace_run.py analyze *), Bash(python3 *claimtrace_run.py ask *), Bash(python3 *claimtrace_run.py doctor), Bash(claimtrace --help), Read, Glob
---

Check these documents with ClaimTrace: $ARGUMENTS

If no folder or files were given, ask which folder to check (default: the current directory) before running.

Use the `claimtrace` skill and follow its hard rules. If the runner reports `engine_not_installed`, follow the
skill: ask the user once before `install --yes`; the install command is deliberately not pre-approved here. Run its runner on all the documents in one call:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/claimtrace/scripts/claimtrace_run.py" analyze $ARGUMENTS
```

(If `${CLAUDE_PLUGIN_ROOT}` is not set, the runner is at `skills/claimtrace/scripts/claimtrace_run.py` inside this
plugin's folder.)

Then present, in this order:

1. One line: which documents were read (title, type, which one each amendment amends) and any warnings or
   skipped files.
2. The register of current obligations: who owes what to whom, by when, with section numbers, then the verbatim
   quotes.
3. Wording replaced by an amendment, with the note that amendment results need a human check (0.60 verdict
   accuracy on unseen amendment wording).
4. Cross-document findings, highest severity first, each with both verbatim quotes and the recommended action;
   then the "not addressed" count, which does not mean an obligation was missed.
5. "ClaimTrace is a reading aid, not legal advice."

Only report what the engine returned with `quote_verified: true`. Never paraphrase a quote.
