# Frontend/UX engineer

## Top 3 concerns
- §7 lists 7+ top-level views (Library, Document with 4 tabs, Deadlines, Ask, Verify, Review queue, Report) as a flat set. Review is a state of items, not a destination: J5 shows reviewers working on findings and answers that live in Verify and Ask. Three places to review the same object will drift. I disagree with a separate "Review queue" as primary nav because users will not know where an item "lives"; the risk is orphaned unreviewed findings.
- "Quote highlighted in its passage" (J1) is under-specified. Offsets are into *normalised* text (§3.3, Span), but PDFs are what users see. Without a source-page view, "verbatim" quotes look unverifiable. Multi-passage quotes, hyphenation, tables, and a quote split across pages will break naive highlighting; a mismatch silently erodes the trust mechanism in §10.
- The Graph tab (§7, J2 graph_path) is the costliest and least decision-useful view. Force-directed graphs are inaccessible to screen readers and unreadable beyond ~50 nodes. The J2 path `Vendor -made_by-> C-12 -requires-> Deadline` is a sentence, not a graph. I disagree with spending v0.1 effort here.

## Top 3 recommendations
- Collapse IA to 4 destinations: Library, Document (Commitments / Deadlines / Definitions as tabs, with a Source pane), Ask, Verify. Make Review a filter plus a persistent count badge everywhere; Report is an action on a document or run, not a view.
- Build one shared `EvidenceQuote` component: quote, section, page, "show in document" opening a side-by-side source pane with `<mark>`, plus an explicit "quote could not be located" state. Use it in every view so evidence rendering is identical.
- Render graph_path as a linear breadcrumb list (accessible as an ordered list); defer the interactive graph, offering at most a read-only "related items" table per commitment.

## Must-have v0.1 requirements
- Keep React + Vite SPA, served as static files by FastAPI: one container, no Node runtime, no SSR needs for a self-hosted single-user tool. Next.js adds a server and a deploy surface for nothing.
- Every async state has copy: parsing, analysing (aria-live polite, with progress counts), failed (reason and retry), scanned PDF flagged (§3 non-goals), zero commitments found ("not the same as none exist"), not_addressed (J3).
- Keyboard: skip link, focus moves to results after Ask/Verify, visible focus (WCAG 2.2 2.4.11), 24px targets (2.5.8), no drag-only interactions, `<mark>` highlights not colour-only.
- Status badges carry text plus icon; verdict/severity vocabulary is identical in UI, report, and API.
- Print stylesheet and HTML report share components; test with a screen reader (NVDA/VoiceOver) and axe in CI.

## Defer (and why)
- Interactive graph visualisation: cost high, accessibility poor, no persona job depends on it.
- Inline PDF rendering with pixel-accurate boxes: text-pane highlight with page jump suffices until OCR/layout arrives (v0.2).
- Calendar or timeline Deadlines widget: a sorted, filterable table serves the PM persona first.
- Dark mode and i18n: tokenise colours and externalise strings now, ship later.

## Failure modes to test
- Quote spans a page break, ligatures, smart quotes, or soft hyphens: highlight misses or lands on wrong occurrence of a repeated phrase.
- 500-commitment document: register without virtualisation or grouping freezes; filters lose state on back-navigation.
- Analysis takes minutes and the user navigates away or refreshes: status lost, duplicate runs.
- Answer with status needs_human_review rendered as confidently as stated; low-confidence badge missed by colour-blind or screen-reader users.
- Document deleted while an answer citing it is open: dangling citations rather than a clear message.
