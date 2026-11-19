# Privacy and data handling

Contracts contain personal data (signatories, contacts, sometimes salaries or bank details). ClaimTrace is
designed so that you control all of it.

## What leaves your machine

**Nothing, by default.** There is no telemetry, no update check, no web fonts and no CDN. A test fails if the
default configuration opens any non-loopback connection.

Two features can send data, and both are off by default:

| Feature | When it sends | What it sends | Control |
|---|---|---|---|
| Language model | Only if `CLAIMTRACE_LLM_PROVIDER` is set | Passages of the document being analysed, and questions with retrieved passages | A non-local endpoint (anything other than localhost/Ollama on this machine) also requires the document's `allow_external_llm` flag. Every send is recorded locally (host, document ID, bytes, purpose, time — no content) at `GET /privacy/egress`. The endpoint host is shown in `/health` and stored in each item's provenance. |
| URL ingestion | Only if `CLAIMTRACE_ALLOW_URL_INGESTION=true` | A GET request to the URL you give | SSRF protections in [security.md](security.md). |

## The browser page, the claude.ai skill and the Claude Code plugin (v0.3)

The table above is about the local app and Docker. v0.3 adds three ways to run the same engine without installing
the app, and where your documents go differs a lot between them:

| Path | Where the engine runs | Where your documents go | What is kept |
|---|---|---|---|
| **Try it page** (`/try/` on the project site) | In your browser tab (Pyodide, WebAssembly) | **Nowhere.** Files are read by code in the tab and never uploaded. The page downloads the engine (about 18 MB) from the same site, and its Content-Security-Policy only allows connections to that site; the end-to-end test fails if any request leaves the local origin. GitHub Pages, which hosts the site, sees ordinary page requests (IP address, user agent), not your files. | Nothing after you close the tab. The browser may cache the engine files, not your documents. |
| **claude.ai skill** (`claimtrace-skill.zip`) | In Anthropic's code-execution sandbox | **To Anthropic.** The files you attach to the chat, and the results the engine returns, are processed by Claude under your Claude plan's terms (retention and training settings as for any chat). The skill starts by reminding you of this. | Whatever your Claude plan keeps for a chat. The runner itself writes nothing to disk (in-memory SQLite) and uses no network. |
| **Claude Code plugin** | On your computer | **Partly to Anthropic.** The files stay on your disk, but the quotes and results the engine prints, and any file Claude opens, become part of the conversation and are processed under your Claude plan or API terms. | Nothing by the runner (in-memory). If you agree to the one-time install, a private copy of ClaimTrace v0.3.0 is kept in the plugin's data folder; deleting the folder removes it. |

The install is the only step in these paths that uses the network on its own: the plugin asks you first, and runs
`pip install` from GitHub only after you agree. If your documents must not leave your machine, use the local app,
Docker, or the Try it page. Details: [claude.md](claude.md#where-do-my-documents-go).

## What is stored, where

Everything lives in one SQLite file (`CLAIMTRACE_DB`, default `./data/claimtrace.db`; in Docker, the
`claimtrace-data` volume).

| Data | Stored? | Notes |
|---|---|---|
| Original uploaded file | **No** | Only normalised text is kept (data minimisation). |
| Normalised document text and passages | Yes | Needed to verify quotes. |
| Filename | Yes (sanitised) | Never logged. |
| Extracted items, graph edges | Yes | Quotes are copies of document text. |
| Questions and answers | Yes | Linked to every document they cite. |
| Review decisions and notes | Yes | Notes may contain personal data. |
| Logs | stdout only | IDs, counts, durations; never text, questions, notes or filenames. |
| Eval runs | `evals/runs/` | Synthetic data only. The runner reads only the bundled datasets. |

## Deletion

`DELETE /documents/{id}` (or **Delete** in the UI, or `claimtrace delete <id>`) removes the document's text,
passages, extracted items, edges, every answer that cited it, every verification run involving it, and all
review decisions and notes on those items. The database is then checkpointed and vacuumed so deleted content
does not linger in free pages or the write-ahead log. A test plants a canary string, deletes the document, and
searches the raw database files for it.

A **content-free tombstone** remains (document ID, checksum, time, reason, counts) at
`GET /privacy/tombstones`, so an audit trail can show that a document existed and was deleted without keeping
its content.

Outside ClaimTrace's control, and therefore your responsibility: exported reports, backups of the data volume,
copies held by an external LLM provider you enabled, and your operating system's swap or disk snapshots.

## Retention

Set `CLAIMTRACE_RETENTION_DAYS=N` to delete documents uploaded more than N days ago. The check runs at
startup and then hourly, and uses the same deletion path as above.

## Recommendations for self-hosters

- Use full-disk encryption; ClaimTrace does not encrypt the database file itself.
- Prefer a local model (Ollama) over a hosted API for confidential documents.
- If you use a hosted provider, check its retention and training terms and where it processes data.
- Keep the default loopback binding unless you have set `CLAIMTRACE_API_TOKEN` and put TLS in front.
