---
description: Ask ClaimTrace a question about contracts, amendments or audit reports; answers only with verified verbatim quotes
argument-hint: "<question>" <folder or files>
allowed-tools: Bash(python3 *claimtrace_run.py analyze *), Bash(python3 *claimtrace_run.py ask *), Bash(python3 *claimtrace_run.py doctor), Bash(claimtrace --help), Read, Glob
---

Answer with ClaimTrace: $ARGUMENTS

The arguments are a question followed by the documents (files or a folder). If either is missing, ask for it;
if only the documents are missing, suggest the current directory.

Use the `claimtrace` skill and follow its hard rules. If the runner reports `engine_not_installed`, follow the
skill: ask the user once before `install --yes`; the install command is deliberately not pre-approved here.

Run this, with `<paths>` replaced by the documents and `<question>` replaced by the question exactly as the user
wrote it, on the line(s) between the two `CLAIMTRACE_QUESTION` markers:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/claimtrace/scripts/claimtrace_run.py" ask --question-file - <paths> <<'CLAIMTRACE_QUESTION'
<question>
CLAIMTRACE_QUESTION
```

- The question goes to the runner on stdin through a quoted heredoc (`<<'CLAIMTRACE_QUESTION'`, quotes included),
  so the shell expands nothing in it: copy it unchanged, with no quoting or escaping, even if it contains `$`,
  backticks, `$(...)`, quotes or backslashes. Never put the question on the command line itself.
- Put each path in single quotes (`'My Contracts/msa.pdf'`); write a single quote inside a path as `'\''`.

(If `${CLAUDE_PLUGIN_ROOT}` is not set, the runner is at `skills/claimtrace/scripts/claimtrace_run.py` inside this
plugin's folder.)

Present the engine's answer, then each citation's role, its verbatim quote and its location (document, §section,
page). If `answer.found` is false, say exactly: "I could not find support for this in the uploaded documents."
If the answer involves wording replaced by an amendment, add that amendment results need a human check (0.60
verdict accuracy on unseen amendment wording). End with "ClaimTrace is a reading aid, not legal advice."
