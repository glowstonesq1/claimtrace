# Security

Threat model, controls, and the tests that hold them in place. For reporting a vulnerability, see
[SECURITY.md](../SECURITY.md).

## Threat model (v0.1)

ClaimTrace is a single-user, self-hosted tool. Uploaded documents are **attacker-controlled input**: a
counterparty writes the contract you upload. The assets are the documents, their derived data and the
integrity of answers. Adversaries considered: a malicious document author, a malicious web page in the
same browser as the user, and a host on the same network.

Out of scope for v0.1: multi-tenant isolation, authenticated multi-user access control, compromised host OS.

## Controls

| Threat | Control | Where | Test |
|---|---|---|---|
| Parser exploits, decompression bombs, pathological PDFs | Parsing in a separate process with CPU (30 s), memory (1 GB), file-descriptor and wall-clock (60 s) limits; generic error message on crash | `packages/ingestion/sandbox.py` | `test_sandbox_contains_parser_crash` |
| XXE / billion laughs in DOCX | Every XML part pre-parsed with `defusedxml` (DTDs, entities and external references forbidden); python-docx's own parser does not resolve entities | `parsers.check_docx_container` | `test_docx_entity_attacks_rejected` |
| Zip bombs | Per-member compression ratio > 100:1 (for members > 1 MB) and total uncompressed size > 50 MB rejected; nested archives rejected | same | `test_docx_zip_bomb_rejected` |
| Active content | Reject DOCX with macros, OLE/ActiveX or external templates; reject PDFs with JavaScript, launch actions, embedded files, rich media or XFA; reject encrypted PDFs | `parsers.py` | `test_docx_macros_rejected`, `test_pdf_with_javascript_rejected` |
| Type confusion | Extension **and** magic bytes must agree; UTF-8 required for text; 20 MB upload cap enforced while streaming | `detect_kind`, `_read_capped` | `test_type_mismatch_and_unsupported`, `test_oversized_upload_rejected` |
| SSRF via URL ingestion | **Off by default.** http/https on ports 80/443 only, no credentials in URLs; all resolved addresses must be global (blocks private, loopback, link-local incl. 169.254.169.254, multicast, reserved, IPv4-mapped IPv6); connect to the **validated IP** with the original Host header and TLS SNI (defeats DNS rebinding between check and use); every redirect re-validated, max 3; 20 MB / 15 s caps; HTML responses refused | `ingestion/url.py` | `test_ssrf.py` (rebinding, redirect, metadata, mapped IPv6) |
| Indirect prompt injection | Document text is wrapped in `<untrusted_document>` delimiters, the model is told it is data; model output is schema-validated; every quote is located by our code in stored text; the model has no tools and no actions exist for it to trigger; passages with instruction-like text are flagged and (since v0.2) never included in a model prompt; LLM-only items quoting them are dropped | `extraction/llm.py`, `verification/ask.py`, `core/models.excluded_from_llm` | `test_llm_boundary.py`, `test_injected_instructions_are_just_text` |
| Hidden text (v0.2) | PDF text drawn white or near-white (lightest channel ≥ 0.95), in render mode 3 (invisible), under 2 pt, or positioned outside the page's media box, and DOCX runs with `w:vanish`/`w:specVanish`, white colour or size under 2 pt are recorded on the passage (`Passage.hidden_text`). The document gets a `HIDDEN:` warning; commitments from those passages are low confidence, need review, and carry a "Hidden text" caveat; the passages are never sent to a model | `parsers._pdf_page_text`, `parsers._docx_hidden`, `rules._build_commitment` | `test_hidden_text.py` |
| Verbatim-but-misleading quotes | Stage-2 grounding: exceptions, "notwithstanding", "subject to" and a qualifying next sentence cap confidence and add caveats; condition clauses link to the clause they qualify | `rules.py` | `test_condition_clause_qualifies_its_subject` |
| Stored XSS | React renders text nodes only (CI fails on `dangerouslySetInnerHTML`); HTML report escapes every field and sets CSP `default-src 'none'`; app CSP forbids inline scripts | `apps/web`, `report.render_html` | `test_xss_is_inert_in_reports_and_csv` |
| CSV formula injection | Cells starting with `= + - @` are prefixed with `'` | `report.deadlines_csv` | same |
| Drive-by requests from other sites (CSRF) to localhost | Unsafe methods require a same-origin `Origin` (or none); no permissive CORS | `SecurityMiddleware` | `test_cross_origin_unsafe_requests_refused` |
| DNS rebinding against localhost | Host header must be a loopback name (or an allowlisted host) when running unauthenticated | same | `test_dns_rebinding_host_refused` |
| Network exposure | Binds `127.0.0.1` by default; refuses to start on another address without `CLAIMTRACE_API_TOKEN`; Compose publishes on `127.0.0.1` only; container runs as non-root, read-only root FS, all capabilities dropped | `create_app`, `docker-compose.yml` | `test_non_loopback_without_token_refuses_to_start`, `test_token_auth` |
| Abuse / runaway clients | Per-client token-bucket rate limit (default 120/min); retries with backoff for LLM calls | middleware, `integrations/llm.py` | `test_rate_limit` |
| Secrets and content in logs | JSON logs with IDs, counts and durations only; validation errors never echo values; 500s return a generic message; API key never returned by `/health` | `apps/api/main.py` | `test_no_outbound_network_and_no_content_in_logs`, `test_structured_errors` |
| Supply chain | Pinned web dependencies (lockfile); CI licence gate (no GPL/AGPL at runtime); `pip-audit` advisory; no model weights are loaded (no pickle); the parser stack avoids AGPL PyMuPDF | `ci.yml` | CI |

## Known gaps (tracked on the roadmap)

- Hidden-text detection does not see text hidden behind images or shapes, text the same colour as a
  coloured background, clipping paths, or DOCX text hidden through a paragraph or character *style* (only
  direct run formatting is read). White text on a dark background is flagged although it is visible.
- The injection detector is a pattern list; it will miss paraphrased or encoded instructions.
- No hash-pinned Python lockfile yet; `pip-audit` is advisory.
- The rate limiter is per process and in memory.
- The bearer token is a single shared secret; there are no user accounts.
- Docker image build is in CI but was not exercised in the v0.1 release environment (no Docker daemon).
