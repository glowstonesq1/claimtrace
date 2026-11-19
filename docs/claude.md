# Use ClaimTrace in Claude

You can use ClaimTrace inside Claude without installing the ClaimTrace app:

- **In claude.ai** (the Claude website and apps): add the ClaimTrace skill once, then attach documents to a chat
  and ask. No install on your computer.
- **In Claude Code** (Claude in a terminal): install the ClaimTrace plugin.

Both run the same ClaimTrace engine as the app. Claude only reports what the engine finds, quotes the documents
word for word with section numbers, and says "I could not find support for this in the uploaded documents" when
the engine finds nothing.

> **Not legal advice.** ClaimTrace helps you read documents. It does not decide what is true, what is legally
> binding, or what you should do.

**Privacy first.** When you use the claude.ai skill, the documents you attach are sent to Anthropic and processed
under your Claude plan's terms. If your documents must stay on your computer, use the
[local app](../README.md) or the [Try it page](https://glowstonesq1.github.io/claimtrace/try/) instead. The table
[below](#where-do-my-documents-go) compares the options.

## Use the skill in claude.ai

You need a Claude plan that offers Skills, with code execution turned on. Work and school accounts may need an
administrator to allow skills.

1. **Download the skill.** Open the latest release at
   <https://github.com/glowstonesq1/claimtrace/releases/latest>. Under "Assets", download
   **`claimtrace-skill.zip`**. Do not unzip it.
2. **Turn on code execution.** In claude.ai, open **Settings → Capabilities** and turn on code execution (it
   may be called "Code execution and file creation"). The skill runs a small program, so it needs this.
3. **Upload the skill.** On the same page, under **Skills**, choose **Upload skill** and pick
   `claimtrace-skill.zip`. "claimtrace" now appears in your list of skills. Make sure it is switched on.
4. **Start a new chat and attach your documents.** Attach the contract and its amendments, audit reports or
   delivery records together (PDF with selectable text, Word .docx, Markdown or plain text). Attach all related
   documents in the same message, so the amendments are matched to the contract they change.
5. **Ask.** For example:
   - "Check this contract and its amendment."
   - "What are the obligations? Who owes what to whom, and by when?"
   - "Did the amendment change the delivery date?"
   - "Does the audit report support what the contract says about data?"

On first use in a chat, Claude reminds you that attached documents are processed by Anthropic. Then it shows:

- **A register**: who owes what to whom, by when, with the section number and the exact quote.
- **Answers** with word-for-word quotes and section numbers, or "I could not find support for this in the uploaded
  documents".
- **Cross-document findings**: for example, a commitment the audit report contradicts, or a deadline the delivery
  record missed, with both quotes.

**Check amendment results yourself.** On amendment wording it had not seen before, the engine's verdict accuracy
was 0.60 (95% interval 0.51 to 0.70, 105 cases). Claude says this whenever it reports what an amendment changed.

**If something goes wrong:**

| You see | What to do |
|---|---|
| Claude doesn't use the skill | Say "Use the ClaimTrace skill" in your message, and check the skill is switched on. |
| "pydantic is not installed" or "lxml" | The code sandbox is missing a package ClaimTrace needs. Use the local app or the Try it page. |
| "No readable text was found" (SCANNED) | The PDF is a scan without a text layer. The local app can read scans with OCR. |
| The answer is "I could not find support…" | The engine found no supporting text. Try other words, or attach the missing document. |

To update the skill, download the new `claimtrace-skill.zip` from the latest release, delete the old skill in
**Settings → Capabilities → Skills**, and upload the new one.

## Where do my documents go?

| | claude.ai skill | Claude Code plugin | Local app | Try it page (browser) |
|---|---|---|---|---|
| Where the engine runs | Anthropic's code sandbox | Your computer | Your computer | Your browser |
| Documents sent to Anthropic | **Yes**: the files you attach, and the results | **Partly**: the files stay on your disk, but the quotes and results the engine prints, and any file Claude opens, go into the conversation | No | No |
| Processed under | Your Claude plan's terms (retention and training settings as for any chat) | Your Claude plan or API terms | Nothing leaves your machine. An optional language model is off by default; an external one needs opt-in per document | Nothing is uploaded; the page downloads the engine from GitHub Pages |
| Install needed | No (upload a zip once) | Claude Code, plus the plugin | Python or Docker | No |
| Keeps a library between sessions | No: each request starts from the attached files | No | Yes, a local database | No |
| Review trail, exports (Markdown, HTML, calendar) | No | No | Yes | See the Try it page |
| Reads scanned PDFs (OCR) | No | Only with the local app installed | Yes, with Tesseract installed | No |

Pick the local app or the Try it page when documents are confidential and must not leave your machine.

## For developers: the Claude Code plugin

### Install

```text
/plugin marketplace add glowstonesq1/claimtrace
/plugin install claimtrace@claimtrace
```

Restart Claude Code if asked. The plugin adds:

- the `claimtrace` skill (the same `SKILL.md` as the claude.ai skill),
- `/claimtrace:claimtrace-check <folder or files>`: register, cross-document findings and quotes for a folder,
- `/claimtrace:claimtrace-ask "<question>" <folder or files>`: one question, answered with verified quotes.

### Which engine runs

The skill always calls `skills/claimtrace/scripts/claimtrace_run.py`, which prints JSON and picks the engine itself
(`engine.source` in its output):

1. **installed**: if a working `claimtrace` command is on your `PATH`, the runner re-runs itself with that
   command's Python, so it uses your installed version. Parsing then runs in ClaimTrace's resource-limited
   subprocess, as in the app.
2. **plugin-venv**: the private engine installed with your permission (see below), in the plugin's data folder
   (`$CLAUDE_PLUGIN_DATA`, else `~/.local/share/claimtrace-claude-plugin/engine-v0.3.0`).
3. **bundled**: the engine copy in `skills/claimtrace/vendor/` (in the release zips), with in-process parsing.
4. **source-checkout**: in a clone of this repository (`claude --plugin-dir plugins/claimtrace`), it uses
   `packages/` directly.
5. **none**: the runner stops with `engine_not_installed` (exit 5) and installs nothing.

`vendor/` is built, not committed, so a plugin installed from the marketplace usually lands in case 5 on a machine
without ClaimTrace. Claude then asks you once whether to install ClaimTrace **v0.3.0** (the git tag
`v0.3.0`, pinned in the runner as `INSTALL_TAG`) from GitHub into that private folder. It needs network access and
about 50 MB. Only if you agree does Claude run `claimtrace_run.py install --yes`, which creates a virtual
environment there (`python -m venv`) and runs
`pip install "claimtrace @ git+https://github.com/glowstonesq1/claimtrace@v0.3.0"` inside it; nothing else on your
system changes. The plugin's slash commands do not pre-approve `install`, so Claude Code also asks for permission
before running it. `install --yes --dry-run` shows the steps without running them. To remove it, delete the folder.
If you prefer, install ClaimTrace yourself (`pipx install 'git+https://github.com/glowstonesq1/claimtrace@v0.3.0'`)
or load the release's `claimtrace-plugin.zip`, which includes the engine: `claude --plugin-dir claimtrace-plugin.zip`.

Maintainers: the tag `v0.3.0` must exist when this plugin version is published, and `INSTALL_TAG` in
`claimtrace_run.py` moves with each release.

Force an engine with `--engine installed|bundled` or `CLAIMTRACE_ENGINE`. `claimtrace_run.py doctor` reports what
would run and what is missing. The runner uses an in-memory store (`:memory:`), configures no language model, and
never imports fastapi, uvicorn or httpx (a stub stands in for httpx where it is not installed).

### Runner commands

```bash
python3 claimtrace_run.py analyze <files or folders...>     # register + cross_document findings
python3 claimtrace_run.py ask "<question>" <files...>       # answer + verified citations
python3 claimtrace_run.py verify <base> <other>             # one pair
python3 claimtrace_run.py doctor                            # which engine would run, what is missing
python3 claimtrace_run.py install --yes [--dry-run]         # only after the user agreed (see above)
```

Every quote in the output carries `quote_verified`, re-checked against the stored text. Items that fail the check
are left out and counted (`dropped_unverified`). Exit codes: 0 ok, 2 usage (or install without --yes), 3 missing dependency, 4 bad input,
5 engine not installed.

### Build the zips

```bash
python scripts/build_skill_zip.py                    # dist/claimtrace-skill.zip, dist/claimtrace-plugin.zip
python scripts/build_skill_zip.py --vendor-in-place  # also fill plugins/claimtrace/skills/claimtrace/vendor/
```

The engine files come from `packages/` through the `pyproject.toml` package mapping. The CLI, eval runner and API
are left out. The pure-Python dependencies (pypdf, python-docx, defusedxml) are added as wheels at the versions
in `requirements.lock`, and their sha256 hashes are checked against it. Compiled dependencies (pydantic with
pydantic_core, and lxml for `.docx`) are not bundled: the runner checks for them at start-up and says what is
missing. The zip is reproducible (fixed timestamps, sorted entries). CI builds both zips on every run, keeps them
as the `claimtrace-skill` artifact, and attaches them to each published GitHub release.

`tests/test_skill_bundle.py` builds the zip and unzips it. It then runs the runner on `examples/documents` in a
fresh virtual environment that has only pydantic and lxml, with sockets and subprocesses blocked. It also checks
the manifests and, if the `claude` CLI is present, runs `claude plugin validate`.

### Assumptions about claude.ai's sandbox (not verified from this repository)

- It runs Python 3.11 or newer, with `pydantic` 2 and `lxml` preinstalled.
- Attached files are readable inside the sandbox, usually under `/mnt/user-data/uploads/`.
- No network access is needed or assumed.

If one of these does not hold, the runner stops with a plain message, and Claude points you to the local app or
the Try it page.
