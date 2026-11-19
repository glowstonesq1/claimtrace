// The evidence map, drawn with React Flow (@xyflow/react): one column per document, its clauses as cards, a
// link between two clauses for every replacement, contradiction or support the engine found. Problems are
// shown first; "Everything" adds the clauses nothing questions. Choosing a clause opens its verbatim words
// and what links to it beside the map. Every link is also listed as text below it.
//
// Keyboard: one tab stop. Arrow keys move along a document and between documents, Home and End jump within
// one; the map follows the focus. Document text is untrusted: React only ever sets it as text.
import {
  Background, BaseEdge, Controls, EdgeLabelRenderer, getBezierPath, Handle, Position, ReactFlow, ReactFlowProvider,
  useReactFlow, type Edge, type EdgeProps, type Node, type NodeProps,
} from "@xyflow/react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Icon } from "./Icon";
import {
  badgeOf, cite, COL_GAP, GRAVITY, layout, LINK, linkWord, NODE_H, NODE_W, PROBLEM, sec, secWords, visible,
  type Clip, type GraphData, type IconName, type Lane, type Link, type Tone,
} from "./model";

export type FlowOptions = {
  /** lane keys to show (default: all) */
  lanes?: string[];
  /** the clause the map opens on */
  selected?: string;
  /** clause ids to keep lit; the rest are dimmed (null: none dimmed) */
  highlight?: string[] | null;
  /** "issues": only clauses a problem touches (default when that is fewer than all); "all": every clause */
  view?: "issues" | "all";
  onSelect?: (clip: Clip, lane: Lane) => void;
  /** adds "Show the finding" to links that carry one, and makes their wires clickable */
  onLink?: (link: Link) => void;
  /** accessible name of the map */
  label?: string;
};

type ClipData = {
  clip: Clip; lane: Lane; badge: [string, IconName, Tone]; tabStop: boolean; pressed: boolean; dim: boolean;

  onKey: (e: React.KeyboardEvent, id: string) => void; onPick: (id: string) => void;
};
type LaneData = { lane: Lane; count: number };
type WireData = { link: Link; lit: boolean; dim: boolean; clickable: boolean; bus?: { y: number; x1: number; x2: number } };

/** A polyline with rounded corners, as an SVG path. */
function rounded(pts: [number, number][], r = 10): string {
  let d = `M${pts[0][0]} ${pts[0][1]}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [p0, p1, p2] = [pts[i - 1], pts[i], pts[i + 1]];
    const l1 = Math.hypot(p1[0] - p0[0], p1[1] - p0[1]), l2 = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);
    const k = Math.min(r, l1 / 2, l2 / 2);
    if (!l1 || !l2) continue;
    d += ` L${p1[0] - ((p1[0] - p0[0]) / l1) * k} ${p1[1] - ((p1[1] - p0[1]) / l1) * k}`;
    d += ` Q${p1[0]} ${p1[1]} ${p1[0] + ((p2[0] - p1[0]) / l2) * k} ${p1[1] + ((p2[1] - p1[1]) / l2) * k}`;
  }
  const z = pts[pts.length - 1];
  return `${d} L${z[0]} ${z[1]}`;
}

function ClipNode({ data }: NodeProps<Node<ClipData>>) {
  const { clip: c, lane, badge } = data;

  const [word, icon, tone] = badge;
  const title = c.node === "answer" ? "The answer" : c.node === "absent" ? "Not mentioned" : [sec(c), c.heading].filter(Boolean).join("  ");
  const name = c.node === "answer" ? `The answer: ${word}` : c.node === "absent" ? `${lane.name}: nothing matches`
    : `${lane.name} ${secWords(c)}${c.heading ? `, ${c.heading}` : ""}: ${word}`;
  return (
    <>
      <Handle type="target" position={Position.Left} id="l" isConnectable={false} />
      <Handle type="source" position={Position.Right} id="r" isConnectable={false} />
      <Handle type="target" position={Position.Right} id="rt" isConnectable={false} />
      <Handle type="source" position={Position.Left} id="ls" isConnectable={false} />
      <button type="button" data-clip={c.id}
        className={`fx-clip fx-clip--${tone}${c.node ? ` fx-clip--${c.node}` : ""}${data.pressed ? " is-on" : ""}${data.dim ? " is-dim" : ""}`}
        tabIndex={data.tabStop ? 0 : -1} aria-pressed={data.pressed} aria-label={name}
        onClick={() => data.onPick(c.id)} onKeyDown={(e) => data.onKey(e, c.id)}>
        <span className="fx-clip__row">
          <span className="fx-clip__top">{title}</span>
          <span className={`fx-badge fx-badge--${tone}`}><Icon name={icon} />{word}</span>
        </span>
        <span className="fx-clip__text">{c.withheld ? "Wording on Try it" : c.node === "absent" ? lane.name : c.text}</span>
      </button>
    </>
  );
}

function LaneNode({ data }: NodeProps<Node<LaneData>>) {
  return (
    <div className="fx-lane" data-lane={data.lane.key}>
      <span className="fx-lane__name">{data.lane.name}</span>
      <span className="fx-lane__count">{data.count} {data.count === 1 ? "clause" : "clauses"}</span>
    </div>
  );
}

function Wire(p: EdgeProps<Edge<WireData>>) {
  const { link, lit, dim, clickable, bus } = p.data!;
  // a link that skips a column runs up a gutter, over the top of the map and down the next gutter, so it never
  // crosses a card
  const [path, lx, ly] = bus
    ? [rounded([[p.sourceX, p.sourceY], [bus.x1, p.sourceY], [bus.x1, bus.y], [bus.x2, bus.y], [bus.x2, p.targetY], [p.targetX, p.targetY]]),
      (bus.x1 + bus.x2) / 2, bus.y]
    : getBezierPath(p);
  const [word, icon, tone] = linkWord(link.kind);
  return (
    <>
      <BaseEdge id={p.id} path={path} interactionWidth={clickable ? 18 : 0}
        className={`fx-wire fx-wire--${link.kind} fx-wire--${tone}${lit ? " is-lit" : ""}${dim ? " is-dim" : ""}`} />
      {lit && (
        <EdgeLabelRenderer>
          <span className={`fx-wire-label fx-badge fx-badge--${tone}`} aria-hidden="true"
            style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}><Icon name={icon} />{word}</span>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const nodeTypes = { clip: ClipNode, lane: LaneNode };
const edgeTypes = { wire: Wire };
const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

function FlowMap({ data: raw, options: o }: { data: GraphData; options: FlowOptions }) {
  const rf = useReactFlow();
  const uid = useId().replace(/:/g, "");
  const data = useMemo<GraphData>(() => (o.lanes ? { ...raw, lanes: raw.lanes.filter((l) => o.lanes!.includes(l.key)) } : raw), [raw, o.lanes]);
  const all = useMemo(() => visible(data, "all"), [data]);
  const issues = useMemo(() => visible(data, "issues"), [data]);
  const count = (v: { lanes: Lane[] }) => v.lanes.reduce((n, l) => n + l.clips.length, 0);
  const canSplit = count(issues) > 0 && count(issues) < count(all);
  const [view, setView] = useState<"issues" | "all">(o.view ?? (canSplit ? "issues" : "all"));
  const shown = view === "issues" && canSplit ? issues : all;
  const { placed, boxes, width, height } = useMemo(() => layout(shown.lanes, shown.links), [shown]);

  const firstProblem = data.links.find((l) => PROBLEM.has(l.kind))?.to;
  const pick0 = [o.selected, firstProblem, shown.lanes[0]?.clips[0]?.id].find((id) => id && placed.has(id))!;
  const [sel, setSel] = useState<string>(pick0);
  const current = placed.has(sel) ? sel : pick0;
  const [said, setSaid] = useState("");
  useEffect(() => { if (o.selected) setSel(o.selected); }, [o.selected]);

  const canvas = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState(0);

  // the canvas is as tall as the map needs at the zoom that fits its width, within limits
  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox(el.clientWidth));
    ro.observe(el);
    setBox(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  // room above the map for links that skip a column (they run over the top)
  const skips = shown.links.filter((l) => placed.has(l.from) && placed.has(l.to)
    && Math.abs(placed.get(l.from)!.col - placed.get(l.to)!.col) > 1).length;
  const over = skips ? 22 + 14 * skips : 0;
  // the whole map at the largest zoom that fits the width and a comfortable height; past that, drag to see more
  const maxH = Math.min(720, Math.max(360, Math.round((typeof innerHeight === "number" ? innerHeight : 900) * 0.8)));
  // on a phone the map is an overview that fits the width; tap a clause to read it in the panel below
  const zoom = box ? Math.max(box < 640 ? 0.3 : 0.7, Math.min(1, (box - 32) / width, (maxH - 40) / (height + over))) : 1;
  const canvasH = Math.round(Math.max(260, Math.min(maxH, (height + over) * zoom + 40)));
  useEffect(() => {
    if (!box) return;
    rf.setViewport({ x: Math.max(16, (box - width * zoom) / 2), y: 20 + over * zoom, zoom });
  }, [rf, box, width, zoom, over, view]);

  const links = shown.links.filter((l) => placed.has(l.from) && placed.has(l.to));
  const hl = o.highlight ? new Set(o.highlight) : null;

  const choose = useCallback((id: string, how: "pointer" | "key") => {
    const p = placed.get(id);
    if (!p) return;
    setSel(id);
    const b = badgeOf(p.clip, data.links);
    setSaid(`${p.clip.node === "answer" ? "The answer" : `${p.lane.name} ${sec(p.clip)}`.trim()}, ${b[0].toLowerCase()}.`);
    o.onSelect?.(p.clip, p.lane);
    if (how === "key") {
      canvas.current?.querySelector<HTMLButtonElement>(`[data-clip="${CSS.escape(id)}"]`)?.focus({ preventScroll: true });
      const z = rf.getZoom();
      rf.setCenter(p.x + NODE_W / 2, p.y + NODE_H / 2, { zoom: z, duration: reduced() ? 0 : 240 });
    }
  }, [placed, data.links, o, rf]);

  // keys move from the chosen clause, which a quick second key press can reach before the cards re-render
  const chosen = useRef(current);
  chosen.current = current;
  const onKey = useCallback((e: React.KeyboardEvent, id: string) => {
    const p = placed.get(placed.has(chosen.current) ? chosen.current : id)!;
    const col = [...placed.values()].filter((q) => q.col === p.col).sort((a, b) => a.y - b.y);
    const at = col.indexOf(p);
    const near = (dc: number) => [...placed.values()].filter((q) => q.col === p.col + dc)
      .sort((a, b) => Math.abs(a.y - p.y) - Math.abs(b.y - p.y))[0];
    const to = ({
      ArrowDown: col[at + 1], ArrowUp: col[at - 1], ArrowRight: near(1), ArrowLeft: near(-1),
      Home: col[0], End: col[col.length - 1],
    } as Record<string, typeof p | undefined>)[e.key];
    if (e.key in { ArrowDown: 1, ArrowUp: 1, ArrowRight: 1, ArrowLeft: 1, Home: 1, End: 1 }) {
      e.preventDefault();
      if (to) { chosen.current = to.clip.id; choose(to.clip.id, "key"); }
    }
  }, [placed, choose]);

  const nodes: Node[] = [];
  for (const b of boxes) {
    nodes.push({ id: `lane:${b.lane.key}`, type: "lane", position: { x: b.x - 12, y: b.y }, data: { lane: b.lane, count: b.count },
      selectable: false, draggable: false, focusable: false, width: NODE_W + 24, height: b.h, zIndex: -1 });
  }
  for (const p of placed.values()) {
    nodes.push({ id: p.clip.id, type: "clip", position: { x: p.x, y: p.y }, draggable: false, selectable: false,
      // fixed sizes: without them React Flow hides each card until it has measured it again, on every
      // render, and a hidden card loses keyboard focus
      focusable: false, width: NODE_W, height: NODE_H, zIndex: 10,
      data: { clip: p.clip, lane: p.lane, badge: badgeOf(p.clip, data.links), tabStop: p.clip.id === current,
        pressed: p.clip.id === current, dim: hl ? !hl.has(p.clip.id) : false, onKey,

        onPick: (id: string) => choose(id, "pointer") } satisfies ClipData });
  }
  let buses = 0;
  const edges: Edge[] = links.map((l, i) => {
    const a = placed.get(l.from)!, b = placed.get(l.to)!;
    const skip = Math.abs(a.col - b.col) > 1;
    const half = COL_GAP / 2;
    const bus = skip ? { y: -18 - 14 * buses++,
      x1: a.col < b.col ? a.x + NODE_W + half : a.x - half, x2: a.col < b.col ? b.x - half : b.x + NODE_W + half } : undefined;
    // left to right, right to left, or an arc on the right between two documents stacked in one column
    const [sh, th] = a.col === b.col ? ["r", "rt"] : a.col < b.col ? ["r", "l"] : ["ls", "rt"];
    return { id: `w${i}`, source: l.from, target: l.to, type: "wire", sourceHandle: sh, targetHandle: th, focusable: false, selectable: false,
      data: { link: l, lit: l.from === current || l.to === current, clickable: !!(o.onLink && l.finding != null),
        dim: hl ? !(hl.has(l.from) && hl.has(l.to)) : false, bus } satisfies WireData };
  });

  const cur = placed.get(current);
  const kinds = GRAVITY.filter((k) => links.some((l) => l.kind === k));
  const capped: string[] = [];
  const s = data.shown || {};
  if (s.documents && s.documents[0] < s.documents[1]) capped.push(`${s.documents[0]} of ${s.documents[1]} documents`);
  if (s.clips && s.clips[0] < s.clips[1]) capped.push(`${s.clips[0]} of ${s.clips[1]} clauses`);
  const problems = data.links.filter((l) => PROBLEM.has(l.kind)).length;

  return (
    <div className="fx">
      <div className="fx-bar">
        {canSplit ? (
          <div className="fx-seg" role="group" aria-label="Which clauses to show">
            <button type="button" aria-pressed={view === "issues"} onClick={() => setView("issues")}>
              Problem clauses <span className="fx-seg__n">{count(issues)}</span></button>
            <button type="button" aria-pressed={view === "all"} onClick={() => setView("all")}>
              All clauses <span className="fx-seg__n">{count(all)}</span></button>
          </div>
        ) : <span />}
        {kinds.length > 0 && (
          <ul className="fx-legend" aria-label="Kinds of link">
            {kinds.map((k) => (
              <li key={k} className={`fx-legend__item fx-wire--${linkWord(k)[2]}`}>
                <svg viewBox="0 0 28 8" aria-hidden="true"><path className={`fx-wire fx-wire--${k} fx-wire--${linkWord(k)[2]}`} d="M1 4h26" /></svg>
                {linkWord(k)[0]}</li>))}
          </ul>
        )}
      </div>
      {capped.length > 0 && <p className="fx-note">Showing {capped.join(" and ")}, the ones with links first. The lists have everything.</p>}
      {view === "issues" && canSplit && (
        <p className="fx-note">{problems} {problems === 1 ? "problem" : "problems"} across {count(issues)} clauses. Choose <strong>All clauses</strong> to see the {count(all) - count(issues)} clauses nothing questions.</p>
      )}
      <div className="fx-body">
        <div className="fx-canvas" ref={canvas} style={{ height: canvasH }} role="group" aria-label={o.label || "Map of the documents"}
          aria-describedby={`${uid}-keys`}>
          <p className="fx-sr" id={`${uid}-keys`}>Each clause is a button. Arrow keys move along a document and between documents; the panel shows the clause in focus and what links to it.</p>
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
            nodesDraggable={false} nodesConnectable={false} nodesFocusable={false} edgesFocusable={false}
            elementsSelectable={false} disableKeyboardA11y deleteKeyCode={null} selectionKeyCode={null}
            multiSelectionKeyCode={null} panActivationKeyCode={null} zoomActivationKeyCode={null}
            zoomOnScroll={false} zoomOnDoubleClick={false} preventScrolling={false} panOnScroll={false}
            minZoom={0.35} maxZoom={1.6} proOptions={{ hideAttribution: true }}
            onEdgeClick={(_, e) => { const l = (e.data as WireData).link; if (o.onLink && l.finding != null) o.onLink(l); else choose(l.to, "pointer"); }}>
            <Background gap={22} size={1} className="fx-dots" />
            <Controls showInteractive={false} position="bottom-right" />
          </ReactFlow>
        </div>
        {cur && <Panel data={data} links={data.links} id={current} lane={cur.lane} clip={cur.clip} onGo={(id) => {
          if (!placed.has(id)) setView("all");
          choose(id, "key");
        }} onLink={o.onLink} />}
      </div>
      <p className="fx-sr" role="status" aria-live="polite">{said}</p>
      <details className="fx-list">
        <summary>Every link as a list <span className="fx-seg__n">{data.links.length}</span></summary>
        <ul>
          {[...data.links].sort((a, b) => GRAVITY.indexOf(a.kind) - GRAVITY.indexOf(b.kind)).map((l, i) => {
            const [word, icon, tone] = linkWord(l.kind);
            return (
              <li key={i} className="fx-list__row">
                <span className={`fx-badge fx-badge--${tone}`}><Icon name={icon} />{word}</span>
                <span>{cite(data, l.to)} {(data.kinds[l.kind]?.in ?? word).toLowerCase()} {cite(data, l.from)}.{l.note ? ` ${l.note}` : ""}
                  {o.onLink && l.finding != null && <> <button type="button" className="fx-link" onClick={() => o.onLink!(l)}>Show the finding</button></>}
                </span>
              </li>);
          })}
        </ul>
      </details>
    </div>
  );
}

function Panel({ data, links, id, lane, clip: c, onGo, onLink }: {
  data: GraphData; links: Link[]; id: string; lane: Lane; clip: Clip; onGo: (id: string) => void; onLink?: (l: Link) => void;
}) {
  const [word, icon, tone] = badgeOf(c, links);
  const mine = links.filter((l) => l.to === id || l.from === id)
    .sort((a, b) => GRAVITY.indexOf(a.kind) - GRAVITY.indexOf(b.kind));
  return (
    <div className="fx-panel">
      <p className="fx-panel__where">
        <span>{c.node === "answer" ? "The answer" : lane.name}</span>
        {!c.node && sec(c) && <span className="fx-num">{sec(c)}</span>}
      </p>
      {!c.node && c.heading && <p className="fx-panel__heading">{c.heading}</p>}
      <p className={`fx-badge fx-badge--${tone}`}><Icon name={icon} />{word}</p>
      {c.node === "answer" ? <p className="fx-panel__answer">{c.text}</p>
        : c.node === "absent" ? <p className="fx-panel__file">Nothing in this document matches the clauses it is linked to. That does not mean they were missed.</p>
        : c.withheld ? <p className="fx-panel__file">Wording not shown on this page. Read it on <a href="try/">Try it</a>, where the full sample contract is loaded.</p>
        : <>
            <blockquote className="fx-panel__quote">{c.text}</blockquote>
            <p className="fx-panel__file">Verbatim from <span className="fx-num">{lane.file || lane.title || lane.name}</span></p>
          </>}
      <h3 className="fx-panel__h">{mine.length ? "What links to it" : "Links"}</h3>
      {!mine.length ? (
        <p className="fx-panel__file">{c.node === "answer" ? "The answer quotes no clause." : "Nothing in the other documents links to this clause."}</p>
      ) : (
        <ul className="fx-panel__links">
          {mine.map((l, i) => {
            const incoming = l.to === id, other = incoming ? l.from : l.to;
            const [w, ic, t] = LINK[l.kind] ?? linkWord(l.kind);
            return (
              <li key={i}>
                <span className={`fx-badge fx-badge--${t}`}><Icon name={ic} />{w}</span>
                <span className="fx-panel__link">
                  {data.kinds[l.kind]?.[incoming ? "in" : "out"] ?? w}{" "}
                  <button type="button" className="fx-link" onClick={() => onGo(other)}>{cite(data, other)}</button>
                  {l.note && <span className="fx-panel__note">{l.note}</span>}
                  {onLink && l.finding != null && <button type="button" className="fx-link fx-panel__finding" onClick={() => onLink(l)}>Show the finding</button>}
                </span>
              </li>);
          })}
        </ul>
      )}
    </div>
  );
}

export function EvidenceFlow({ data, options }: { data: GraphData; options: FlowOptions }) {
  return <ReactFlowProvider><FlowMap data={data} options={options} /></ReactFlowProvider>;
}

