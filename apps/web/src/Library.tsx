import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Badge } from "./components";
import { DOC_TYPE_LABEL, DOC_TYPES } from "./labels";
import { Skeleton } from "./motion";
import type { Doc } from "./types";

export function Library({ go }: { go: (hash: string) => void }) {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [over, setOver] = useState(false);
  const [docType, setDocType] = useState("");
  const [amends, setAmends] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const load = () => api.documents().then(setDocs).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const pollRun = async (poll: string) => {
    for (let i = 0; i < 600; i++) {
      const run = await api.run(poll);
      if (run.status === "done" || run.status === "failed") return run;
      await new Promise((r) => setTimeout(r, 1000));
    }
    return null;
  };

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setError("");
    for (const file of Array.from(files)) {
      const form = new FormData();
      form.append("file", file);
      if (docType) form.append("doc_type", docType);
      if (amends) form.append("amends_document_id", amends);
      try {
        setStatus(`Reading ${file.name}…`);
        const doc = await api.upload(form);
        setStatus(`Finding commitments in “${doc.title}”…`);
        const { poll } = await api.analyze(doc.id);
        const run = await pollRun(poll);
        setStatus(run?.status === "done"
          ? `Done: “${doc.title}” — ${run.counts.commitments ?? 0} commitments found, ${run.counts.needs_review ?? 0} need your review.`
          : `Analysis of “${doc.title}” did not finish${run?.error ? `: ${run.error}` : "."}`);
      } catch (e) {
        setError(`${file.name}: ${(e as Error).message}`);
        setStatus("");
      }
    }
    load();
  };

  const loadSamples = async () => {
    setStatus("Loading sample documents…");
    try { await api.samples(); setStatus("Sample documents loaded and analysed."); load(); }
    catch (e) { setError((e as Error).message); setStatus(""); }
  };

  const remove = async (d: Doc) => {
    if (!window.confirm(`Delete “${d.title}” and everything found in it? This cannot be undone.`)) return;
    try { await api.remove(d.id); setStatus(`Deleted “${d.title}”.`); load(); } catch (e) { setError((e as Error).message); }
  };

  const contracts = (docs ?? []).filter((d) => d.doc_type !== "amendment");
  return (
    <>
      <h1>Your documents</h1>
      <section aria-labelledby="up-h" className="card">
        <h2 id="up-h" className="flush">Add a document</h2>
        <p className="muted">PDF (with selectable text), Word (.docx), Markdown or plain text. Files stay on this computer
          unless you have turned on an external AI service.</p>
        <div className="row">
          <div className="field">
            <label htmlFor="dtype">What kind of document is it?</label>
            <select id="dtype" value={docType} onChange={(e) => setDocType(e.target.value)}>
              <option value="">Work it out from the file</option>
              {DOC_TYPES.map((t) => <option key={t} value={t}>{DOC_TYPE_LABEL[t]}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="amends">Does it change another document?</label>
            <select id="amends" value={amends} onChange={(e) => setAmends(e.target.value)}>
              <option value="">No</option>
              {contracts.map((d) => <option key={d.id} value={d.id}>Yes, it amends “{d.title}”</option>)}
            </select>
            <div className="help">Choose this for amendments and variations, so changed terms are tracked.</div>
          </div>
        </div>
        <div className={`drop ${over ? "over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files); }}>
          <p>Drag files here, or</p>
          <button type="button" className="primary" onClick={() => fileRef.current?.click()}>Choose files</button>
          <input ref={fileRef} type="file" multiple accept=".pdf,.docx,.md,.markdown,.txt" className="sr"
            aria-label="Choose files to upload" onChange={(e) => upload(e.target.files)} />
        </div>
        <div role="status" aria-live="polite" className="status-line">{status}</div>
        {error && <div className="errbox" role="alert">{error}</div>}
      </section>

      {docs === null && !error && <Skeleton label="Loading your documents…" lines={["w-30", "w-95", "w-95", "w-95"]} />}
      {docs && docs.length === 0 && (
        <section className="card">
          <h2 className="flush">Nothing here yet</h2>
          <p>Try the bundled example: a fictional contract, an amendment that changes three terms, an audit report and a
            delivery record.</p>
          <button type="button" className="primary" onClick={loadSamples}>Load sample documents</button>
        </section>
      )}

      {docs && docs.length > 0 && (
        <section aria-labelledby="lib-h">
          <h2 id="lib-h">Library</h2>
          <div className="table-wrap"><table>
            <caption className="sr">Uploaded documents</caption>
            <thead><tr><th scope="col">Document</th><th scope="col">Kind</th><th scope="col">Version</th>
              <th scope="col">Status</th><th scope="col"><span className="sr">Actions</span></th></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td>
                    <a href={`#/doc/${d.id}`}>{d.title}</a>
                    {d.amends_document_id && <div className="small muted">Amends “{docs.find((x) => x.id === d.amends_document_id)?.title ?? "another document"}”</div>}
                    {d.warnings.filter((w) => /^(SCANNED|INJECTION)/.test(w)).map((w) => (
                      <div key={w} className="small note">Warning: {w.replace(/^\w+: /, "")}</div>))}
                  </td>
                  <td>{DOC_TYPE_LABEL[d.doc_type] ?? d.doc_type}</td>
                  <td>{d.version_label}</td>
                  <td>{d.status === "analyzed" ? <Badge tone="ok" icon="check">Ready</Badge>
                    : d.status === "failed" ? <Badge tone="bad" icon="cross">Failed</Badge>
                    : <Badge tone="info">{d.status === "parsed" ? "Not analysed yet" : "Working…"}</Badge>}</td>
                  <td className="actions">
                    {d.status === "parsed" && <button type="button" onClick={async () => { const { poll } = await api.analyze(d.id); await pollRun(poll); load(); }}>Analyse</button>}{" "}
                    <button type="button" className="danger" onClick={() => remove(d)} aria-label={`Delete ${d.title}`}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div>
          <p className="small muted">Next: open a document to see its commitments, <a href="#/ask" onClick={() => go("#/ask")}>ask a question</a>, or <a href="#/verify">check two documents against each other</a>.</p>
        </section>
      )}
    </>
  );
}
