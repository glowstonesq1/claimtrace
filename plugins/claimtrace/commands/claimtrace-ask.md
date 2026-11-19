---
description: Ask ClaimTrace a question about contracts, amendments or audit reports; answers only with verified verbatim quotes
argument-hint: "<question>" <folder or files>
allowed-tools: Bash(python3 *claimtrace_run.py*), Bash(claimtrace --help), Read, Glob
---

Answer with ClaimTrace: $ARGUMENTS

The arguments are a question followed by the documents (files or a folder). If either is missing, ask for it;
if only the documents are missing, suggest the current directory.

Use the `claimtrace` skill and follow its hard rules. Run, with the question quoted exactly as the user wrote it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/claimtrace/scripts/claimtrace_run.py" ask "<question>" <folder or files>
```

(If `${CLAUDE_PLUGIN_ROOT}` is not set, the runner is at `skills/claimtrace/scripts/claimtrace_run.py` inside this
plugin's folder.)

Present the engine's answer, then each citation's role, its verbatim quote and its location (document, §section,
page). If `answer.found` is false, say exactly: "I could not find support for this in the uploaded documents."
If the answer involves wording replaced by an amendment, add that amendment results need a human check (0.60
verdict accuracy on unseen amendment wording). End with "ClaimTrace is a reading aid, not legal advice."
