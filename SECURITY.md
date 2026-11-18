# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting ("Report a vulnerability"
on the Security tab) for this repository. Include the version, configuration (e.g. URL ingestion or model
provider enabled) and a minimal reproduction. Please don't include real confidential documents; a synthetic
file that triggers the issue is enough.

We aim to acknowledge reports within 3 working days, agree on a fix timeline within 10, and publish an
advisory with credit (if you want it) when a fix is released.

Particularly welcome: parser escapes or resource-limit bypasses, SSRF bypasses, ways to make ClaimTrace show
an unverified quote, ways to make a document change a verdict through injected instructions, and leaks of
document content into logs or exports after deletion.

The threat model and controls are documented in [docs/security.md](docs/security.md).
