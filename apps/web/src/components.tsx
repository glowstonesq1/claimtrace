import { useState } from "react";
import { api } from "./api";
import { REVIEW, where } from "./labels";
import { toast } from "./motion";
import type { Span } from "./types";

const ICONS: Record<string, string> = {
  check: "M3 8.5l3 3L13 5", cross: "M4 4l8 8M12 4l-8 8", dash: "M4 8h8", half: "M8 2a6 6 0 100 12z",
  question: "M6 6a2 2 0 114 0c0 1.5-2 1.5-2 3M8 12v.5", eye: "M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5zM8 10a2 2 0 100-4 2 2 0 000 4z",
};

export function Badge({ tone, icon, children, title }: { tone: string; icon?: string; children: React.ReactNode;
  title?: string }) {
  return (
    <span className={`badge tone-${tone}`} title={title}>
      {icon && (
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" fill={icon === "half" ? "currentColor" : "none"}
          stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d={ICONS[icon]} /></svg>
      )}
      {children}
    </span>
  );
}

/** The one way evidence is shown everywhere: verbatim quote + location + "show in document". */
export function EvidenceQuote({ span, role = "supports", note, onShow, verified = true, superseded }: {
  span: Span; role?: string; note?: string | null; onShow?: (s: Span) => void; verified?: boolean; superseded?: boolean;
}) {
  return (
    <figure className="evidence">
      <blockquote className={`quote ${role === "conflicts" ? "conflicts" : role === "context" ? "context" : ""} ${superseded ? "superseded" : ""}`}>
        “{span.quote}”
      </blockquote>
      <figcaption className="loc">
        <span>
          {role === "conflicts" && <strong>Conflicting source: </strong>}
          {role === "context" && <strong>Context: </strong>}
          {role === "checked_not_supporting" && <strong>Checked, does not answer: </strong>}
          {where(span)}
        </span>
        {note && <span>{note}</span>}
        {!verified && <span><strong>Quote could not be located in the stored text</strong></span>}
        {onShow && <button type="button" className="btn small" onClick={() => onShow(span)}>Show in document</button>}
      </figcaption>
    </figure>
  );
}

export function reviewerName(): string {
  try { return localStorage.getItem("ct_reviewer") || ""; } catch { return ""; }
}

/** Append-only review controls. Names are self-declared in v0.1 and labelled that way in reports. */
export function ReviewControls({ kind, id, status, lifecycle }: { kind: "answers" | "findings" | "commitments"; id: string;
  status: string; lifecycle?: boolean }) {
  const [current, setCurrent] = useState(status);
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");
  const send = async (decision: string, extra: Record<string, string> = {}) => {
    let name = reviewerName();
    if (!name) {
      name = window.prompt("Your name (recorded with your review):")?.trim() || "";
      if (!name) return;
      try { localStorage.setItem("ct_reviewer", name); } catch { /* storage unavailable */ }
    }
    try {
      await api.review(kind, id, { decision, reviewer: name, note: note || undefined, ...extra });
      const map: Record<string, string> = { accept: "accepted", reject: "rejected", request_evidence: "needs_evidence", resolve: "resolved" };
      if (map[decision]) setCurrent(map[decision]);
      setMsg(decision === "note" ? "Note saved." : "Saved."); setNote("");
      toast(decision === "note" ? "Note saved to the review trail" : `Review saved: ${REVIEW[map[decision]] ?? "updated"}`);
    } catch (e) { setMsg((e as Error).message); }
  };
  return (
    <div>
      <div className="small muted">Your review: <strong>{REVIEW[current] ?? current}</strong></div>
      <div className="review" role="group" aria-label="Review this item">
        <button type="button" onClick={() => send("accept")}>Looks right</button>
        <button type="button" onClick={() => send("reject")}>Wrong</button>
        <button type="button" onClick={() => send("request_evidence")}>Need evidence</button>
        {lifecycle
          ? <button type="button" onClick={() => send("resolve", { lifecycle: "fulfilled" })}>Mark done</button>
          : <button type="button" onClick={() => send("resolve")}>Mark handled</button>}
      </div>
      <div className="row" style={{ marginTop: "var(--space-xs)" }}>
        <div className="field" style={{ flex: "3 1 260px", marginBottom: 0 }}>
          <label htmlFor={`note-${id}`} className="small">Add a note</label>
          <input id={`note-${id}`} value={note} onChange={(e) => setNote(e.target.value)} maxLength={4000} />
        </div>
        <button type="button" disabled={!note} onClick={() => send("note")}>Save note</button>
      </div>
      <div role="status" aria-live="polite" className="small">{msg}</div>
    </div>
  );
}
