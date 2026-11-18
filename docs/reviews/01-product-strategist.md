# Product strategist

## Top 3 concerns
- No wedge user. §2 lists six personas and §3 ships a library, register, ask, verify, review and report. I disagree with serving all of them: Ironclad/Kira/Luminance own enterprise CLM and diligence, and Harvey/Spellbook own lawyers inside Word. ClaimTrace has no beachhead and no one-sentence answer to "why not ChatGPT with the PDF?". §1's "generic AI chat gives no quote" is a weak moat, because Claude and ChatGPT projects now cite passages.
- The default experience is the rules extractor (§10, "Rules baseline first"). First-run J1 ("18 items") will have low recall on real contracts. A local-first user with no LLM key sees worse output than pasting the PDF into a chat tool, and never reaches the verbatim-quote feature that is the actual differentiator. The risk is a failed first impression.
- Open-source economics are unaddressed. §12 has no row for adoption, maintainer load, or who runs the thing. Docker Compose plus SQLite plus a React app asks a non-technical ops owner (the J1 persona) to self-host. The people who can self-host are developers, so the personas and the distribution contradict each other.

## Top 3 recommendations
- Pick one wedge: "amendment drift". The user is a procurement or ops person holding a contract plus its amendments who needs to know which date or term now governs. J4 is the only journey no chat tool does reliably, because it needs persistent multi-document state and a review trail. Make J4 the demo and cut the other personas from v0.1 messaging.
- Make the LLM path first-class in the recommended setup. Resolve open question (1) by shipping a one-command "bring your own key or Ollama" path. Keep the rules baseline as an offline floor and as the eval anchor, not as the product default.
- Ship as a CLI and library plus a minimal UI, and ask for contributions through the eval set (external cases and a plugin API pulled forward from v1.0). Distribution comes from developers building on trustworthy provenance primitives, which matches the "Developer" persona row.

## Must-have v0.1 requirements
- A published head-to-head on the same synthetic amendment set, comparing ClaimTrace with a bare LLM prompt. The metrics are hallucinated-quote rate, not-found accuracy and contradiction recall. Without it the switch argument is unproven.
- J4 (verify across an amendment pair, with `supersedes` status propagating to the register and to `/ask` caveats) working end to end with an LLM extractor.
- Time to first useful result under 5 minutes, measured, including install.
- A visible "what we did not check" statement on every report, so a pass is never read as clearance.
- Real contracts of the kind users will upload (not only the synthetic set), run privately by maintainers, to estimate real recall before launch.

## Defer (and why)
- Claims, graph view, and the full 13-type edge taxonomy: they are provenance plumbing, and no one switches tools for them.
- Evidence-gap/audit-report verification (§1 bullet 3, researcher persona): a second wedge that dilutes the first.
- URL ingestion, retention purge, rate limiting: security surface with no adoption payoff.
- Report HTML polish; ICS export stays in v0.2.

## Failure modes to test
- A user compares ClaimTrace with a ChatGPT upload on the same MSA plus amendment and cannot tell which is better from the outputs.
- The rules extractor returns few items on a real contract and the user concludes the tool is broken.
- A user trusts a "consistent" verdict when the matcher missed the changed clause (a false clear is worse than a false alarm).
- A non-technical user abandons at `docker compose up`.
- Review fatigue: more than 30% of items flagged "Needs review", so the register is no faster than reading the PDF.
