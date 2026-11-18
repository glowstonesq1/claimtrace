// Keyboard-accessible relationship graph (roadmap v1.0). Hand-rolled layered layout:
// parties (who) -> commitments (what) -> documents (where it is written). No graph library.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { EFFECT, TYPE } from "./labels";
import type { Commitment, Doc, GraphData, Passage, Span } from "./types";

type Kind = "party" | "commitment" | "document";
type GNode = { id: string; kind: Kind; col: 0 | 1 | 2; label: string; name: string; detail: string[]; changed: boolean;
  span: Span | null; x: number; y: number; w: number };
type GEdge = { id: string; src: string; dst: string; rel: Rel };
type Rel = "made_by" | "owed_to" | "supersedes" | "amends" | "qualifies" | "references" | "contains";

/** Plain-language wording for each relationship, read from the source side and from the target side. */
const REL: Record<Rel, [string, string]> = {
  made_by: ["Who must act", "Must do"],
  owed_to: ["Owed to", "Is owed"],
  supersedes: ["Replaces", "Replaced by"],
  amends: ["Changes", "Changed by"],
  qualifies: ["Limits", "Limited by"],
  references: ["Mentions", "Mentioned in"],
  contains: ["Written in", "Contains"],
};
const COLS = [{ x: 8, w: 150, head: "Who" }, { x: 214, w: 336, head: "What was committed to" }, { x: 602, w: 176, head: "Where it is written" }];
const W = 840, TOP = 40, ROW = 34, NODE_H = 26, MIN_GAP = 36;

const clip = (s: string, w: number) => { const n = Math.floor((w - 16) / 7); return s.length > n ? `${s.slice(0, n - 1)}…` : s; };
const secKey = (s: string | null) => (s ?? "999").split(".").map((x) => x.padStart(4, "0")).join(".");

function spread(nodes: GNode[], want: Map<string, number>) {
  nodes.sort((a, b) => (want.get(a.id) ?? 0) - (want.get(b.id) ?? 0));
  let last = -Infinity;
  for (const n of nodes) { n.y = Math.max(want.get(n.id) ?? TOP, last + MIN_GAP); last = n.y; }
}

export function RelationshipGraph({ graph, docId, items, passages, onShow, onSelect }: {
  graph: GraphData; docId: string; items: Commitment[]; passages: Passage[]; onShow: (s: Span) => void;
  /** Called whenever the selected node changes (click, arrow keys, detail-pane links, Escape), with that
   *  node's source span or null, so the source pane never keeps highlighting a previous node's passage. */
  onSelect?: (s: Span | null) => void;
}) {
  const [docs, setDocs] = useState<Doc[]>([]);
  useEffect(() => { api.documents().then(setDocs).catch(() => undefined); }, []);

  const { nodes, edges, height } = useMemo(() => {
    const byId = new Map(items.map((c) => [c.id, c]));
    const docTitle = (id: string) => { const d = docs.find((x) => x.id === id); return d ? `${d.title} (${d.version_label})` : null; };
    const out = new Map<string, GNode>();
    const add = (n: Omit<GNode, "x" | "y" | "w">) => out.set(n.id, { ...n, x: COLS[n.col].x, y: 0, w: COLS[n.col].w });
    const extras = new Map<string, string[]>();   // deadlines and conditions become details on the commitment
    for (const e of graph.edges) {
      const dst = graph.nodes.find((n) => n.id === e.dst_id);
      if (!dst) continue;
      if (e.type === "requires") (extras.get(e.src_id) ?? extras.set(e.src_id, []).get(e.src_id)!).push(`By when: ${dst.label}`);
      if (e.type === "conditioned_on") (extras.get(e.src_id) ?? extras.set(e.src_id, []).get(e.src_id)!).push(`Only if: ${dst.label}`);
    }
    for (const n of graph.nodes) {
      if (n.type === "party") {
        const full = (n as { name?: string }).name;
        add({ id: n.id, kind: "party", col: 0, label: n.label, name: `Party: ${n.label}${full ? `, ${full}` : ""}`,
          detail: full ? [`Defined as ${full}`] : [], changed: false, span: partySpan(passages, docId, full, n.label) });
      } else if (n.type === "commitment" || (n.type === "external" && byId.has(n.id))) {
        const c = byId.get(n.id);
        const kindWord = c ? TYPE[c.type] ?? c.type : n.label;
        const who = c?.obliging_party ?? "no party named";
        const fromOther = c && c.document_id !== docId;
        const changed = !!c && c.document_effect !== "in_force";
        const text = c?.text ?? n.text ?? "";
        add({ id: n.id, kind: "commitment", col: 1,
          label: `§${c?.section_number ?? "?"} ${kindWord}${fromOther ? " (amendment)" : ""}: ${c?.action ?? text}`,
          name: `§${c?.section_number ?? "?"}, ${kindWord.toLowerCase()}, ${who}${fromOther ? ", from an amendment" : ""}: ${text}` +
            (changed ? `. ${EFFECT[c!.document_effect]}` : ""),
          detail: [text, ...(changed ? [EFFECT[c!.document_effect]] : []), ...(extras.get(n.id) ?? [])],
          changed, span: c?.provenance.span ?? null });
      } else if (n.type === "document" || (n.type === "external" && n.id.startsWith("doc_"))) {
        const title = n.type === "document" ? n.label : docTitle(n.id);
        if (!title) continue;
        add({ id: n.id, kind: "document", col: 2, label: title, name: `Document: ${title}`,
          detail: n.id === docId ? ["This document"] : ["Another uploaded document"], changed: false,
          span: n.id === docId ? firstSpan(passages, docId) : { document_id: n.id, passage_id: "", char_start: 0, char_end: 0, quote: "",
            page: null, section: null, document_title: title, document_version: null } });
      }
    }
    const es: GEdge[] = [];
    for (const e of graph.edges) {
      if (!(e.type in REL) || !out.has(e.src_id) || !out.has(e.dst_id)) continue;
      es.push({ id: e.id, src: e.src_id, dst: e.dst_id, rel: e.type as Rel });
    }
    for (const c of items) if (out.has(c.id) && out.has(c.document_id))
      es.push({ id: `in-${c.id}`, src: c.id, dst: c.document_id, rel: "contains" });

    const list = [...out.values()];
    const cmts = list.filter((n) => n.kind === "commitment").sort((a, b) => {
      const ca = byId.get(a.id), cb = byId.get(b.id);
      return secKey(ca?.section_number ?? null).localeCompare(secKey(cb?.section_number ?? null)) ||
        Number(ca?.document_id !== docId) - Number(cb?.document_id !== docId);
    });
    cmts.forEach((n, i) => { n.y = TOP + i * ROW; });
    const avg = (id: string) => {
      const ys = es.filter((e) => e.src === id || e.dst === id).map((e) => out.get(e.src === id ? e.dst : e.src)!)
        .filter((m) => m.kind === "commitment").map((m) => m.y);
      return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : TOP;
    };
    for (const kind of ["party", "document"] as Kind[]) {
      const col = list.filter((n) => n.kind === kind);
      spread(col, new Map(col.map((n) => [n.id, avg(n.id)])));
    }
    const ordered = [...list].sort((a, b) => a.col - b.col || a.y - b.y);
    const bottom = Math.max(TOP, ...ordered.map((n) => n.y)) + NODE_H + 12;
    return { nodes: ordered, edges: es, height: bottom };
  }, [graph, items, docs, passages, docId]);

  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const [active, setActive] = useState<string | null>(null);
  const [focusable, setFocusable] = useState<string | null>(null);
  const [hint, setHint] = useState("");
  const refs = useRef(new Map<string, SVGGElement>());
  const tabStop = focusable && byId.has(focusable) ? focusable : nodes[0]?.id;

  const links = (id: string) => edges.filter((e) => e.src === id || e.dst === id).map((e) => {
    const out = e.src === id;
    return { edge: e, other: byId.get(out ? e.dst : e.src)!, phrase: REL[e.rel][out ? 0 : 1] };
  });
  const lit = new Set<string>();
  if (active) { lit.add(active); for (const l of links(active)) { lit.add(l.edge.id); lit.add(l.other.id); } }

  // Keep the source highlight in step with the selection. Skips the first render so opening the tab does
  // not clear a highlight the user made elsewhere before selecting anything here.
  const selected = active ? byId.get(active) ?? null : null;
  const selectedSpan = selected?.span ?? null;
  const mounted = useRef(false);
  useEffect(() => {
    if (!mounted.current) { mounted.current = true; return; }
    onSelect?.(selectedSpan);
  }, [active, selectedSpan]);

  const focusNode = (id: string) => { setFocusable(id); setActive(id); setHint(""); refs.current.get(id)?.focus(); };
  const open = (n: GNode) => { if (n.span) onShow(n.span); };

  const onKey = (e: React.KeyboardEvent, n: GNode) => {
    const col = nodes.filter((m) => m.col === n.col);
    const i = col.findIndex((m) => m.id === n.id);
    const toSide = (dir: 1 | -1) => {
      const cands = links(n.id).map((l) => l.other).filter((m) => m.col === n.col + dir);
      if (!cands.length) { setHint(`Nothing connected to the ${dir > 0 ? "right" : "left"} of this item.`); return; }
      cands.sort((a, b) => Math.abs(a.y - n.y) - Math.abs(b.y - n.y));
      focusNode(cands[0].id);
    };
    const keys: Record<string, () => void> = {
      ArrowDown: () => col[i + 1] && focusNode(col[i + 1].id),
      ArrowUp: () => col[i - 1] && focusNode(col[i - 1].id),
      ArrowRight: () => toSide(1),
      ArrowLeft: () => toSide(-1),
      Home: () => focusNode(col[0].id),
      End: () => focusNode(col[col.length - 1].id),
      Enter: () => open(n),
      " ": () => open(n),
      Escape: () => setActive(null),
    };
    if (keys[e.key]) { e.preventDefault(); keys[e.key](); }
  };

  const path = (a: GNode, b: GNode) => {
    if (a.col === b.col) {  // same column: an arc bowing out to the right
      const x = a.x + a.w, y1 = a.y + NODE_H / 2, y2 = b.y + NODE_H / 2, bow = 18 + Math.min(36, Math.abs(y2 - y1) / 5);
      return `M${x} ${y1} C${x + bow} ${y1} ${x + bow} ${y2} ${x} ${y2}`;
    }
    const [l, r] = a.col < b.col ? [a, b] : [b, a];
    const x1 = l.x + l.w, y1 = l.y + NODE_H / 2, x2 = r.x, y2 = r.y + NODE_H / 2, dx = (x2 - x1) / 2;
    return `M${x1} ${y1} C${x1 + dx} ${y1} ${x2 - dx} ${y2} ${x2} ${y2}`;
  };
  const cur = active ? byId.get(active) : null;
  if (!nodes.length) return <p className="muted">No relationships were found to draw.</p>;

  return (
    <section aria-labelledby="graph-h">
      <h2 id="graph-h">Map of who owes what</h2>
      <p className="kbd-help" id="graph-help">Select an item, then use <kbd>↑</kbd> <kbd>↓</kbd> to move within a column,{" "}
        <kbd>←</kbd> <kbd>→</kbd> to follow a link to a connected item, and <kbd>Enter</kbd> to show its source text.</p>
      <div className="graph-wrap">
        <svg className={`graph ${active ? "has-active" : ""}`} viewBox={`0 0 ${W} ${height}`} role="group"
          aria-labelledby="graph-h" aria-describedby="graph-help">
          {COLS.map((c) => <text key={c.head} className="col-head" x={c.x} y={18} aria-hidden="true">{c.head}</text>)}
          <g aria-hidden="true">
            {edges.map((e) => {
              const a = byId.get(e.src)!, b = byId.get(e.dst)!;
              const cls = e.rel === "supersedes" ? "replaces" : e.rel === "qualifies" ? "limits" : "";
              return <path key={e.id} d={path(a, b)} className={`edge ${cls} ${lit.has(e.id) ? "lit" : ""}`} />;
            })}
          </g>
          {nodes.map((n) => (
            <g key={n.id} ref={(el) => { if (el) refs.current.set(n.id, el); else refs.current.delete(n.id); }}
              className={`node ${n.kind} ${n.changed ? "changed" : ""} ${n.id === active ? "active" : ""} ${lit.has(n.id) ? "lit" : ""}`}
              data-node={n.id} role="button" tabIndex={n.id === tabStop ? 0 : -1} aria-label={n.name}
              transform={`translate(${n.x} ${n.y})`}
              onFocus={() => { setActive(n.id); setFocusable(n.id); }} onKeyDown={(e) => onKey(e, n)}
              onClick={() => focusNode(n.id)} onDoubleClick={() => open(n)}>
              <rect width={n.w} height={NODE_H} rx={n.kind === "party" ? NODE_H / 2 : 5} />
              <text x={10} y={NODE_H / 2 + 4.5}>{clip(n.label, n.w)}</text>
            </g>))}
        </svg>
      </div>
      <div className="graph-detail card">
        {!cur && <p className="muted">Select an item on the map to see what it is connected to.</p>}
        {cur && (
          <>
            <h3>{cur.kind === "party" ? `Party: ${cur.label}` : cur.kind === "document" ? cur.label : cur.label.split(":")[0]}</h3>
            {cur.detail.map((d) => <p key={d} className="small">{d}</p>)}
            {links(cur.id).length > 0 && (
              <ul className="list-plain" aria-label="Connected items">
                {links(cur.id).map((l) => (
                  <li key={l.edge.id}><button type="button" className="btn small" onClick={() => focusNode(l.other.id)}>
                    {l.phrase}: {clip(l.other.label, 420)}</button></li>))}
              </ul>)}
            {cur.span && <p><button type="button" className="btn small" onClick={() => open(cur)}>
              {cur.kind === "document" && cur.id !== docId ? "Open this document" : "Show in document"}</button></p>}
          </>
        )}
        <p className="small muted" role="status">{hint}</p>
      </div>
    </section>
  );
}

function firstSpan(passages: Passage[], docId: string): Span | null {
  const p = passages[0];
  return p ? { document_id: docId, passage_id: p.id, char_start: p.char_start, char_end: p.char_end, quote: p.text, page: p.page,
    section: p.section_number, document_title: null, document_version: null } : null;
}

/** A party has no stored span; point at the first passage that names it (usually the definition). */
function partySpan(passages: Passage[], docId: string, full: string | undefined, alias: string): Span | null {
  for (const needle of [full, `"${alias}"`, `“${alias}”`, alias].filter(Boolean) as string[]) {
    for (const p of passages) {
      const i = p.text.indexOf(needle);
      if (i >= 0) return { document_id: docId, passage_id: p.id, char_start: p.char_start + i, char_end: p.char_start + i + needle.length,
        quote: needle, page: p.page, section: p.section_number, document_title: null, document_version: null };
    }
  }
  return null;
}
