import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { Badge, EvidenceQuote, ReviewControls } from "./components";
import { RelationshipGraph } from "./Graph";
import { Skeleton } from "./motion";
import { CONFIDENCE, DOC_TYPE_LABEL, EFFECT, REVIEW, TYPE, VERDICT } from "./labels";
import type { Claim, Commitment, Doc, GraphData, Passage, Span, VerificationRun } from "./types";

type Tab = "commitments" | "deadlines" | "claims" | "terms" | "relationships" | "checks";

export function DocumentView({ id }: { id: string }) {
  const [doc, setDoc] = useState<Doc | null>(null);
  const [passages, setPassages] = useState<Passage[]>([]);
  const [extra, setExtra] = useState<{ parties: { name: string; alias: string | null }[];
    definitions: { term: string; definition_text: string }[] }>({ parties: [], definitions: [] });
  const [items, setItems] = useState<Commitment[]>([]);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [checks, setChecks] = useState<VerificationRun[]>([]);
  const [tab, setTab] = useState<Tab>("commitments");
  const [highlight, setHighlight] = useState<Span | null>(null);
  const [pulse, setPulse] = useState(0);  // bumps on every jump so the passage pulses again
  const [error, setError] = useState("");
  const [f, setF] = useState({ party: "", type: "", show: "current", review: "" });
  const sourceRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.document(id).then((r) => { setDoc(r.document); setPassages(r.passages); setExtra(r); })
      .catch((e) => setError(e.message));
    api.commitments(id).then(setItems).catch(() => undefined);
    api.claims(id).then(setClaims).catch(() => undefined);
    api.graph(id).then(setGraph).catch(() => undefined);
    api.verifications(id).then(setChecks).catch(() => undefined);
  }, [id]);
  useEffect(() => {  // deep link from Ask/Verify: #/doc/<id>?p=<passage>
    const pid = new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("p");
    const p = passages.find((x) => x.id === pid);
    if (p) {
      setHighlight({ document_id: id, passage_id: p.id, char_start: p.char_start, char_end: p.char_end, quote: p.text,
        page: p.page, section: p.section_number, document_title: null, document_version: null });
      setPulse((n) => n + 1);
      requestAnimationFrame(() => document.getElementById(`p-${p.id}`)?.scrollIntoView({ block: "center" }));
    }
  }, [passages, id]);

  const show = (s: Span) => {
    setHighlight(s); setPulse((n) => n + 1);
    if (s.document_id !== id) { window.location.hash = `#/doc/${s.document_id}?p=${s.passage_id}`; return; }
    requestAnimationFrame(() => document.getElementById(`p-${s.passage_id}`)?.scrollIntoView({ block: "center" }));
  };
  const parties = useMemo(() => Array.from(new Set(items.map((c) => c.obliging_party).filter(Boolean))) as string[], [items]);
  const visible = items.filter((c) =>
    (!f.party || c.obliging_party === f.party) && (!f.type || c.type === f.type) &&
    (f.show === "all" || (f.show === "current" ? c.document_effect === "in_force" : c.document_effect !== "in_force")) &&
    (!f.review || (f.review === "flagged" ? c.needs_review : c.provenance.review_status === f.review)));
  const flagged = items.filter((c) => c.needs_review && c.provenance.review_status === "unreviewed").length;
  const deadlines = items.filter((c) => c.deadline).sort((a, b) =>
    (a.deadline?.date ?? "9999").localeCompare(b.deadline?.date ?? "9999"));

  if (error) return <div className="errbox" role="alert">{error}</div>;
  if (!doc) return <><Skeleton label="Loading…" lines={["w-60 tall"]} card={false} />
    <div className="split spaced"><Skeleton label="" /><Skeleton label="" lines={["w-80", "w-95", "w-95", "w-60"]} /></div></>;
  const isEvidence = ["audit_report", "evidence", "report"].includes(doc.doc_type);
  const tabs: [Tab, string][] = [["commitments", `Commitments (${items.length})`], ["deadlines", `Deadlines (${deadlines.length})`],
    ...(isEvidence || claims.length ? [["claims", `Statements (${claims.length})`] as [Tab, string]] : []),
    ["terms", "Parties & definitions"], ["relationships", "Relationships"], ["checks", `Checks (${checks.length})`]];

  return (
    <>
      <p className="small"><a href="#/">Back to all documents</a></p>
      <h1>{doc.title}</h1>
      <ul className="meta small" aria-label="About this document">
        <li>{DOC_TYPE_LABEL[doc.doc_type]}</li><li>Version {doc.version_label}</li><li>{passages.length} passages</li>
        {doc.page_count ? <li>{doc.page_count} pages</li> : null}
        <li>SHA-256 <code title={doc.checksum_sha256}>{doc.checksum_sha256.slice(0, 12)}…</code></li></ul>
      {doc.warnings.map((w) => <div key={w} className="warnbox" role="note"><strong>Warning: </strong>{w.replace(/^\w+: /, "")}</div>)}
      {flagged > 0 && <p><Badge tone="warn" icon="eye">{flagged} item{flagged === 1 ? "" : "s"} need your review</Badge>{" "}
        <button type="button" onClick={() => { setTab("commitments"); setF({ ...f, review: "flagged", show: "all" }); }}>Show them</button></p>}
      <div className="meta small" role="group" aria-label="Export">
        <span>Export:</span>
        <a href={`/documents/${id}/report?format=html`} target="_blank" rel="noopener">printable report</a>
        <a href={`/documents/${id}/report?format=md`}>Markdown</a><a href={`/documents/${id}/report?format=json`}>JSON</a>
        <a href={`/documents/${id}/deadlines.csv`}>deadlines (Excel/CSV)</a>
      </div>

      <div className="tabs" role="tablist" aria-label="Document views">
        {tabs.map(([k, label]) => (
          <button type="button" key={k} role="tab" aria-selected={tab === k} aria-controls={`panel-${k}`} id={`tab-${k}`}
            onClick={() => setTab(k)}>{label}</button>))}
      </div>

      <div className="split">
        <section key={tab} className="fade-in" id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`}>
          {tab === "commitments" && (
            <>
              <div className="filters">
                <div><label htmlFor="f-party">Who must act</label>
                  <select id="f-party" value={f.party} onChange={(e) => setF({ ...f, party: e.target.value })}>
                    <option value="">Anyone</option>{parties.map((p) => <option key={p}>{p}</option>)}</select></div>
                <div><label htmlFor="f-type">Kind</label>
                  <select id="f-type" value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}>
                    <option value="">All kinds</option>{Object.entries(TYPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
                <div><label htmlFor="f-show">Show</label>
                  <select id="f-show" value={f.show} onChange={(e) => setF({ ...f, show: e.target.value })}>
                    <option value="current">Current terms</option><option value="changed">Replaced or deleted</option>
                    <option value="all">Everything</option></select></div>
                <div><label htmlFor="f-review">Review</label>
                  <select id="f-review" value={f.review} onChange={(e) => setF({ ...f, review: e.target.value })}>
                    <option value="">Any</option><option value="flagged">Flagged for review</option>
                    {Object.entries(REVIEW).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
              </div>
              <p className="small muted" aria-live="polite">{visible.length} shown. Only text in this document and its uploaded
                amendments is covered.</p>
              {items.length === 0 && <div className="card">No commitments were found. That is not the same as the document
                having none: check that the file has selectable text and try the Ask page.</div>}
              {visible.map((c) => <CommitmentCard key={c.id} c={c} onShow={show} />)}
            </>
          )}
          {tab === "deadlines" && (
            <div className="table-wrap"><table>
              <caption className="sr">Deadlines sorted by date</caption>
              <thead><tr><th scope="col">When</th><th scope="col">Who</th><th scope="col">What</th><th scope="col">Status</th></tr></thead>
              <tbody>{deadlines.map((c) => (
                <tr key={c.id}>
                  <td>{c.deadline?.date ?? <span className="muted">{c.deadline?.raw}</span>}
                    {c.deadline?.date === null && c.deadline?.kind !== "absolute" && <div className="small muted">Not on a calendar: {c.deadline?.kind}</div>}</td>
                  <td>{c.obliging_party ?? <em>no party named</em>}</td>
                  <td><button type="button" className="btn left" onClick={() => show(c.provenance.span)}>§{c.section_number} {c.action.slice(0, 120)}</button></td>
                  <td><Badge tone={c.document_effect === "in_force" ? "ok" : "muted"}>{EFFECT[c.document_effect]}</Badge></td>
                </tr>))}</tbody>
            </table></div>
          )}
          {tab === "claims" && claims.map((c) => (
            <div className="card" key={c.id}><Badge tone="info">{c.claim_type.replace("_", " ")}</Badge>
              <EvidenceQuote span={c.provenance.span} onShow={show} /></div>))}
          {tab === "terms" && (
            <>
              <h2>Parties</h2>
              <ul>{extra.parties.map((p) => <li key={p.name}><strong>{p.alias}</strong> = {p.name}</li>)}</ul>
              {!extra.parties.length && <p className="muted">No defined parties found (looked for patterns like
                Acme Ltd (the "Supplier")).</p>}
              <h2>Definitions</h2>
              <dl>{extra.definitions.map((d) => <div key={d.term}><dt><strong>{d.term}</strong></dt><dd>{d.definition_text}</dd></div>)}</dl>
            </>
          )}
          {tab === "relationships" && graph && (<>
            <RelationshipGraph graph={graph} docId={id} items={items} passages={passages} onShow={show} />
            <Relationships graph={graph} items={items} />
          </>)}
          {tab === "checks" && (
            <>
              {!checks.length && <p>No checks yet. <a href="#/verify">Compare this document with another</a>.</p>}
              {checks.map((r) => (
                <div className="card" key={r.id}>
                  <h3>{r.mode === "amendment" ? "Compared with an amendment" : r.mode === "evidence" ? "Checked against evidence" : "Compared with another document"}</h3>
                  <p className="badges">{Object.entries(r.summary).filter(([, n]) => n).map(([k, n]) =>
                    <Badge key={k} tone={VERDICT[k]?.tone ?? "muted"} icon={VERDICT[k]?.icon}>{VERDICT[k]?.label ?? k}: {n}</Badge>)}</p>
                  <a href={`#/verify?run=${r.id}`}>Open findings</a>
                </div>))}
            </>
          )}
        </section>

        <aside className="card source" aria-label="Document text" ref={sourceRef} tabIndex={0}>
          <h2 className="flush">Document text</h2>
          {passages.map((p) => {
            const hit = !!highlight && highlight.passage_id === p.id;
            const a = hit ? highlight!.char_start - p.char_start : 0;
            const b = hit ? highlight!.char_end - p.char_start : 0;
            return (
              <p key={hit ? `${p.id}-${pulse}` : p.id} id={`p-${p.id}`} className={hit ? "hit pulse" : undefined}>
                {p.page ? <span className="sec">p.{p.page} </span> : null}
                {hit && a >= 0 && b <= p.text.length
                  ? <>{p.text.slice(0, a)}<mark>{p.text.slice(a, b)}</mark>{p.text.slice(b)}</>
                  : p.text}
              </p>);
          })}
        </aside>
      </div>
    </>
  );
}

function CommitmentCard({ c, onShow }: { c: Commitment; onShow: (s: Span) => void }) {
  const replaced = c.document_effect !== "in_force";
  return (
    <article className="card" aria-labelledby={`c-${c.id}`}>
      <h3 id={`c-${c.id}`}>§{c.section_number ?? "?"} {TYPE[c.type]} <span className="muted">({c.obliging_party ?? "no party named"})</span></h3>
      <div className="badges">
        <Badge tone={replaced ? "muted" : "ok"}>{EFFECT[c.document_effect]}</Badge>
        {c.amends_section && <Badge tone="info">From amendment</Badge>}
        {c.needs_review && <Badge tone="warn" icon="eye">Needs your review</Badge>}
        <span className="small muted">{CONFIDENCE[c.confidence]}</span>
      </div>
      <EvidenceQuote span={c.provenance.span} onShow={onShow} superseded={replaced} />
      <dl className="small facts">
        <dt>For whom</dt><dd>{c.beneficiary_party ?? "—"}</dd>
        <dt>By when</dt><dd>{c.deadline ? (c.deadline.date ?? c.deadline.raw) : "—"}</dd>
        {c.conditions.length > 0 && <><dt>Only if</dt><dd>{c.conditions.join("; ")}</dd></>}
        {c.exceptions.length > 0 && <><dt>Unless / except</dt><dd>{c.exceptions.join("; ")}</dd></>}
        {c.performer_party && <><dt>Done by</dt><dd>{c.performer_party}</dd></>}
      </dl>
      {[...c.review_reasons, ...c.caveats].map((r) => <p key={r} className="small note">Note: {r}</p>)}
      <details><summary className="small">How this was found</summary>
        <p className="small muted">Method: {c.provenance.extraction_method}{c.provenance.model ? ` (${c.provenance.model})` : ""}.
          The quote was checked against the stored text.</p></details>
      <ReviewControls kind="commitments" id={c.id} status={c.provenance.review_status} lifecycle />
    </article>
  );
}

const EDGE_LABEL: Record<string, string> = { made_by: "is owed by", owed_to: "is owed to", requires: "has deadline",
  conditioned_on: "only applies if", supersedes: "replaces", amends: "amends", qualifies: "limits", references: "mentions",
  supports: "supports", contradicts: "conflicts with", evidence_for: "is evidence for", depends_on: "depends on",
  duplicates: "duplicates" };

/** Accessible relationship view (design-review D17): a readable table instead of a force-directed graph. */
function Relationships({ graph, items }: { graph: GraphData; items: Commitment[] }) {
  const label = (id: string) => {
    const c = items.find((x) => x.id === id);
    const n = graph.nodes.find((x) => x.id === id);
    if (n?.type === "external" && c) return `§${c.section_number ?? "?"} ${TYPE[c.type] ?? c.type} (amendment)`;
    return n?.label ?? id;
  };
  const groups = graph.edges.reduce<Record<string, typeof graph.edges>>((acc, e) => {
    (acc[e.type] ||= []).push(e); return acc; }, {});
  return (
    <>
      <h2>The same links as a list</h2>
      <p className="muted small">How items in this document connect. {graph.nodes.length} items, {graph.edges.length} links.
        The full graph with provenance is available from the API at /documents/&lt;id&gt;/graph.</p>
      {Object.entries(groups).map(([type, es]) => (
        <section key={type}>
          <h3>{EDGE_LABEL[type] ?? type} ({es.length})</h3>
          <div className="table-wrap"><table><thead><tr><th scope="col">Item</th><th scope="col">Relationship</th><th scope="col">Item</th></tr></thead>
            <tbody>{es.map((e) => <tr key={e.id}><td>{label(e.src_id)}</td><td>{EDGE_LABEL[e.type] ?? e.type}</td><td>{label(e.dst_id)}</td></tr>)}</tbody>
          </table></div>
        </section>))}
    </>
  );
}
