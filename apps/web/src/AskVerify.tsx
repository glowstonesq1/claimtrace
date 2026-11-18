import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Badge, EvidenceQuote, ReviewControls } from "./components";
import { ANSWER, CONFIDENCE, VERDICT } from "./labels";
import { Skeleton } from "./motion";
import type { Answer, Doc, Span, VerificationRun } from "./types";

const showSpan = (s: Span) => { window.location.hash = `#/doc/${s.document_id}?p=${s.passage_id}`; };

function DocPicker({ docs, selected, onChange }: { docs: Doc[]; selected: string[]; onChange: (ids: string[]) => void }) {
  return (
    <fieldset className="card">
      <legend><strong>Search in</strong></legend>
      {docs.map((d) => (
        <label key={d.id} className="check">
          <input type="checkbox" checked={selected.includes(d.id)}
            onChange={(e) => onChange(e.target.checked ? [...selected, d.id] : selected.filter((x) => x !== d.id))} />
          {d.title} <span className="muted small">({d.version_label})</span>
        </label>))}
      <div className="help">Leave everything ticked to search all documents.</div>
    </fieldset>
  );
}

export function Ask() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const out = useRef<HTMLDivElement>(null);
  useEffect(() => { api.documents().then((d) => { setDocs(d); setSelected(d.map((x) => x.id)); }); }, []);

  const ask = async (question: string) => {
    if (question.trim().length < 3) return;
    setBusy(true); setError(""); setQ(question);
    try {
      const a = await api.ask(question, selected.length === docs.length ? undefined : selected);
      setAnswer(a);
      requestAnimationFrame(() => out.current?.focus());
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const examples = ["Did the vendor promise delivery by March 31?", "What are the vendor's obligations?",
    "What happens if the vendor misses the delivery deadline?", "Which commitments changed in the amendment?",
    "Is customer data kept in the UK?", "Which obligations have no supporting evidence?"];
  const st = answer && ANSWER[answer.status];
  return (
    <>
      <h1>Ask the documents</h1>
      <p className="muted">Answers are built only from quotes in your documents. If there is no supporting text, ClaimTrace
        says so instead of guessing.</p>
      {docs.length === 0 && <p>Add a document first on the <a href="#/">Documents</a> page.</p>}
      {docs.length > 0 && <DocPicker docs={docs} selected={selected} onChange={setSelected} />}
      <form onSubmit={(e) => { e.preventDefault(); ask(q); }} className="card">
        <label htmlFor="q">Your question</label>
        <div className="row"><input id="q" value={q} onChange={(e) => setQ(e.target.value)} maxLength={1000}
          placeholder="e.g. When must the supplier deliver?" style={{ flex: "4 1 300px" }} />
          <button type="submit" className="primary" disabled={busy || q.trim().length < 3}>
            {busy ? "Searching…" : "Ask"}</button></div>
        <div className="help examples"><span>Try:</span>{examples.map((x) => <button key={x} type="button"
          className="btn small" onClick={() => ask(x)}>{x}</button>)}</div>
      </form>
      {error && <div className="errbox" role="alert">{error}</div>}
      {busy && <Skeleton label="Searching the documents…" lines={["w-30", "w-95", "w-80", "w-95 tall", "w-60"]} />}
      {!busy && answer && st && (
        <section key={answer.id} className="card reveal" aria-labelledby="ans-h" tabIndex={-1} ref={out}>
          <h2 id="ans-h" className="flush">Answer</h2>
          <p className="badges"><Badge tone={st.tone} icon={st.icon}>{st.label}</Badge><span className="small muted">{CONFIDENCE[answer.confidence]}</span></p>
          <p className="answer-text">{answer.answer_text}</p>
          {answer.citations.length > 0 && <h3>Sources</h3>}
          {answer.citations.map((c, i) => <EvidenceQuote key={i} span={c.span} role={c.role} note={c.note}
            verified={c.verified} onShow={showSpan} />)}
          {answer.graph_path.length > 0 && (<><h3>Where this comes from</h3>
            <ol className="path">{answer.graph_path.map((g, i) => <li key={i}>{g.node}</li>)}</ol></>)}
          {answer.caveats.length > 0 && (<><h3>Things to know</h3><ul>{answer.caveats.map((c) => <li key={c}>{c}</li>)}</ul></>)}
          {answer.follow_ups.length > 0 && (<><h3>You could also ask</h3>
            <ul className="list-plain">{answer.follow_ups.map((f) => <li key={f}><button type="button" className="btn" onClick={() => ask(f)}>{f}</button></li>)}</ul></>)}
          <ReviewControls kind="answers" id={answer.id} status={answer.review_status} />
        </section>
      )}
    </>
  );
}

export function Verify({ runId }: { runId?: string }) {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [base, setBase] = useState("");
  const [other, setOther] = useState("");
  const [run, setRun] = useState<VerificationRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showAll, setShowAll] = useState(false);
  const out = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    api.documents().then((d) => { setDocs(d); setBase(d[0]?.id ?? ""); setOther(d[1]?.id ?? ""); });
    if (runId) fetch(`/verifications/${runId}`).then((r) => r.json()).then(setRun).catch(() => undefined);
  }, [runId]);
  const verify = async () => {
    setBusy(true); setError("");
    try { setRun(await api.verify(base, other)); requestAnimationFrame(() => out.current?.focus()); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const title = (id: string) => docs.find((d) => d.id === id)?.title ?? id;
  const order = ["contradicted", "partially_supported", "needs_human_review", "ambiguous", "not_addressed", "consistent"];
  const findings = run ? [...run.findings].sort((a, b) => order.indexOf(a.verdict) - order.indexOf(b.verdict)) : [];
  const important = findings.filter((f) => f.severity !== "info");
  const shown = showAll ? findings : important;
  return (
    <>
      <h1>Check documents against each other</h1>
      <p className="muted">Compare a contract with an amendment, a proposal, an audit report or a delivery record. Every
        finding shows the exact text it is based on. A “Matches” result on evidence means matching text was found; you
        still decide whether it is enough.</p>
      <div className="card">
        <div className="row">
          <div className="field"><label htmlFor="base">Main document (usually the contract)</label>
            <select id="base" value={base} onChange={(e) => setBase(e.target.value)}>
              {docs.map((d) => <option key={d.id} value={d.id}>{d.title} ({d.version_label})</option>)}</select></div>
          <div className="field"><label htmlFor="other">Compare with</label>
            <select id="other" value={other} onChange={(e) => setOther(e.target.value)}>
              {docs.map((d) => <option key={d.id} value={d.id}>{d.title} ({d.version_label})</option>)}</select></div>
          <button type="button" className="primary" disabled={busy || !base || !other || base === other} onClick={verify}>
            {busy ? "Checking…" : "Check"}</button>
        </div>
        {base && base === other && <p className="small note">Choose two different documents.</p>}
      </div>
      {error && <div className="errbox" role="alert">{error}</div>}
      {busy && <>{[0, 1, 2].map((i) => <Skeleton key={i} label={i === 0 ? "Checking the documents…" : ""} />)}</>}
      {!busy && run && (
        <section aria-labelledby="res-h">
          <h2 id="res-h" tabIndex={-1} ref={out}>Findings: {title(run.base_document_id)} vs {title(run.other_document_id)}</h2>
          <p className="badges">{order.filter((k) => run.summary[k]).map((k) => (
            <span key={k}><Badge tone={VERDICT[k].tone} icon={VERDICT[k].icon}>{VERDICT[k].label}: {run.summary[k]}</Badge></span>))}</p>
          <label className="check">
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
            Also show unchanged and matching items ({findings.length - important.length})</label>
          {shown.map((f, i) => {
            const v = VERDICT[f.verdict];
            return (
              <article className="card stagger" style={{ "--i": i } as React.CSSProperties} key={f.id} aria-labelledby={`f-${f.id}`}>
                <h3 id={`f-${f.id}`}><Badge tone={v.tone} icon={v.icon}>{v.label}</Badge>{" "}
                  <span className="small muted">Importance: {f.severity}</span></h3>
                <p><strong>What was checked:</strong></p>
                {f.subject_span ? <EvidenceQuote span={f.subject_span} onShow={showSpan} /> : <p>{f.subject_text}</p>}
                <p><strong>Result:</strong> {f.explanation}</p>
                {f.supporting.map((s, i) => <EvidenceQuote key={`s${i}`} span={s} role="supports" onShow={showSpan} />)}
                {f.conflicting.map((s, i) => <EvidenceQuote key={`c${i}`} span={s} role="conflicts" onShow={showSpan} />)}
                {f.sufficiency && <p className="small"><Badge tone="info">You decide</Badge> Whether this evidence is sufficient is a judgement for you.</p>}
                <p><strong>Suggested next step:</strong> {f.recommended_action}</p>
                <ReviewControls kind="findings" id={f.id} status={f.review_status} />
              </article>);
          })}
          {shown.length === 0 && <p>No conflicts, gaps or uncertain items. {findings.length} items were checked.</p>}
          <p className="small muted">Only the two selected documents were compared; other documents were not considered.</p>
        </section>
      )}
    </>
  );
}
