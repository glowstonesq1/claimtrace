// The evidence map's model (built by claimtrace.browser.graphs on the engine side) and how it is laid out:
// one column per document, its clauses stacked in it, links drawn between columns. Shared by the site's
// map (site.tsx) and anything else that draws lanes, clips and links.

export type Clip = {
  id: string; section?: string | null; heading?: string | null; text: string; kinds?: string[];
  effect?: string; state?: string; parties?: string[]; node?: "answer" | "absent"; status?: string; withheld?: boolean;
};
export type Lane = { key: string; name: string; title?: string; file?: string; clips: Clip[] };
export type Link = { from: string; to: string; kind: string; note?: string; severity?: string; finding?: number };
export type GraphData = {
  lanes: Lane[]; links: Link[]; kinds: Record<string, { in: string; out: string }>;
  shown?: { documents?: [number, number]; clips?: [number, number] };
};

export type Tone = "replaced" | "contra" | "partly" | "review" | "current" | "neutral" | "none";

// link kind -> [word, icon, tone]. A status is always a word and an icon, never colour alone.
export const LINK: Record<string, [string, IconName, Tone]> = {
  replaces: ["Replaced", "replaced", "replaced"], changes: ["Changed", "replaced", "replaced"],
  replaced: ["Replaced", "replaced", "replaced"], contradicts: ["Contradicted", "contradicts", "contra"],
  conflicts: ["Disagrees", "contradicts", "contra"], partly: ["Partly supported", "partly", "partly"],
  review: ["Needs review", "review", "review"], notfound: ["Not found", "none", "none"],
  notmentioned: ["Not mentioned", "none", "none"], supports: ["Supported", "supports", "current"],
  states: ["States it", "supports", "current"], context: ["Context", "evidence", "neutral"],
};
// clip state -> [word, icon, tone]
const STATE: Record<string, [string, IconName, Tone]> = {
  replaced: ["Replaced", "replaced", "replaced"], in_force: ["In force", "inforce", "current"],
  evidence: ["Evidence", "evidence", "neutral"], review: ["Needs review", "review", "review"],
  absent: ["Not mentioned", "none", "none"],
};
const ANSWER: Record<string, [string, IconName, Tone]> = {
  stated: ["Found in the documents", "supports", "current"], implied: ["Implied, not stated outright", "partly", "partly"],
  contradicted: ["The documents disagree", "contradicts", "contra"], not_addressed: ["Not found in the documents", "none", "none"],
  ambiguous: ["Unclear: more than one reading", "review", "review"],
  needs_human_review: ["A person needs to check this", "review", "review"],
};
// Worst first: when a clause has several links, the badge names the most serious one.
export const GRAVITY = ["contradicts", "conflicts", "replaces", "changes", "replaced", "partly", "review", "notfound",
  "notmentioned", "supports", "states", "context"];
/** Links that are a problem someone should look at; the rest (supports, states, context) are reassurance. */
export const PROBLEM = new Set(["contradicts", "conflicts", "replaces", "changes", "replaced", "partly", "review", "notfound"]);

const SOURCE_SIDE: Record<string, string> = {
  replaces: "New wording", changes: "New wording", contradicts: "Contradicts", conflicts: "Disagrees",
  partly: "Partly supports", review: "Needs review", notfound: "Does not say it", replaced: "Quoted",
};

export type IconName = "replaced" | "contradicts" | "partly" | "supports" | "review" | "inforce" | "none" | "evidence";

export const sec = (c: Clip) => (!c.section ? "" : c.section.startsWith("¶") ? c.section : `§${c.section}`);
export const secWords = (c: Clip) => (!c.section ? "" : c.section.startsWith("¶") ? `paragraph ${c.section.slice(1)}` : `section ${c.section}`);
export const linkWord = (kind: string) => LINK[kind] ?? LINK.review;

/** What a clause's badge says: its own state when it was replaced or flagged, else its worst link. */
export function badgeOf(c: Clip, links: Link[]): [string, IconName, Tone] {
  if (c.node === "answer") return ANSWER[c.status ?? ""] ?? ANSWER.not_addressed;
  if (c.node === "absent") return STATE.absent;
  const st = c.state ?? c.effect ?? "evidence";
  if (st === "replaced" || st === "review") return STATE[st];
  // The clause a link points at reads it from its own side ("Contradicted"); the clause it comes from reads
  // it from the other ("Contradicts"). An amendment clause that replaces another is the new wording.
  const touching = links.filter((l) => l.from === c.id || l.to === c.id);
  const worst = GRAVITY.map((k) => touching.find((l) => l.kind === k)).find(Boolean);
  if (!worst || !PROBLEM.has(worst.kind)) return STATE[st] ?? STATE.evidence;
  if (worst.to === c.id) return LINK[worst.kind];
  const [, icon, tone] = LINK[worst.kind];
  return [SOURCE_SIDE[worst.kind] ?? LINK[worst.kind][0], icon, ["replaces", "changes"].includes(worst.kind) ? "current" : tone];
}

export const NODE_W = 244, NODE_H = 92, COL_GAP = 112, ROW_GAP = 14, HEAD_H = 40, GROUP_GAP = 28;

export type Placed = { clip: Clip; lane: Lane; col: number; row: number; x: number; y: number };
export type Box = { lane: Lane; x: number; y: number; h: number; count: number };

/** Which clauses to draw: everything, or (the default for big maps) only those a problem touches. */
export function visible(data: GraphData, view: "issues" | "all"): { lanes: Lane[]; links: Link[] } {
  if (view === "all") return { lanes: data.lanes.filter((l) => l.clips.length), links: data.links };
  const links = data.links.filter((l) => PROBLEM.has(l.kind));
  const keep = new Set(links.flatMap((l) => [l.from, l.to]));
  const lanes = data.lanes
    .map((l) => ({ ...l, clips: l.clips.filter((c) => keep.has(c.id) || c.node || ["replaced", "review"].includes(c.state ?? c.effect ?? "")) }))
    .filter((l) => l.clips.length);
  return { lanes, links };
}

/** Where each document goes: which column, and which documents share one (stacked). With six documents or
 *  fewer every arrangement into up to four columns is cheap to try, so this tries them all and keeps the one
 *  where the fewest links have to pass over a column of cards, the map is neither too tall nor too wide, and documents keep
 *  their order. On the samples that puts the amendment left of the contract and the reports stacked on its
 *  right: almost every link joins two neighbouring columns. */
export function columns(lanes: Lane[], links: Link[]): { cols: Lane[][]; hub: number } {
  const n = lanes.length;
  if (n <= 2) return { cols: lanes.map((l) => [l]), hub: 0 };
  const laneOf = new Map(lanes.flatMap((l, i) => l.clips.map((c) => [c.id, i] as const)));
  const pairs = links.map((l) => [laneOf.get(l.from), laneOf.get(l.to)]).filter((p): p is [number, number] => p[0] != null && p[1] != null && p[0] !== p[1]);
  let best: { cost: number; at: number[]; k: number } | null = null;
  for (let k = 2; k <= Math.min(n, 4); k++) {
    const at = new Array(n).fill(0);
    for (let m = 0; m < k ** n; m++) {
      for (let i = 0, v = m; i < n; i++, v = Math.floor(v / k)) at[i] = v % k;
      const clips = new Array(k).fill(0);
      lanes.forEach((l, i) => { clips[at[i]] += l.clips.length + 0.5; });
      if (clips.some((c) => c === 0)) continue;
      // a link that skips a column is drawn over the top of the map, one between documents stacked in one
      // column as an arc beside it: both are harder to follow than a link to the next column
      let cost = Math.max(...clips) + k * 2;
      for (const [x, y] of pairs) {
        const d = Math.abs(at[x] - at[y]);
        cost += d === 0 ? 4 : (d - 1) * 3;
      }
      for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) if (at[i] > at[j]) cost += 0.4;
      if (k * (NODE_W + COL_GAP) - COL_GAP > 1100) cost += 6; // too wide to read without zooming out
      if (!best || cost < best.cost - 1e-9) best = { cost, at: [...at], k };
    }
  }
  const cols: Lane[][] = Array.from({ length: best!.k }, () => []);
  lanes.forEach((l, i) => cols[best!.at[i]].push(l));
  return { cols, hub: best!.at[0] };
}

/** The first column keeps document order; every other clause sits as near its partners as it can. */
export function layout(lanes: Lane[], links: Link[]): { placed: Map<string, Placed>; boxes: Box[]; width: number; height: number } {
  const { cols, hub: first } = columns(lanes, links);
  const placed = new Map<string, Placed>();
  const boxes: Box[] = [];
  const partners = (id: string) => links.filter((l) => l.from === id || l.to === id).map((l) => (l.from === id ? l.to : l.from));
  const order = [first, ...cols.map((_, i) => i).filter((i) => i !== first)];
  let height = 0;
  for (const ci of order) {
    const x = ci * (NODE_W + COL_GAP);
    let y = 0, row = 0;
    for (const lane of cols[ci]) {
      const sorted = lane.clips.map((c, i) => {
        const ys = partners(c.id).map((p) => placed.get(p)?.y).filter((v): v is number => v != null);
        return { c, i, key: ci === first || !ys.length ? 1e9 + i : ys.reduce((a, b) => a + b, 0) / ys.length };
      }).sort((a, b) => a.key - b.key || a.i - b.i);
      const top = y;
      y += HEAD_H;
      for (const { c } of sorted) {
        placed.set(c.id, { clip: c, lane, col: ci, row: row++, x, y });
        y += NODE_H + ROW_GAP;
      }
      boxes.push({ lane, x, y: top, h: y - top - ROW_GAP + 12, count: lane.clips.length });
      y += GROUP_GAP;
    }
    height = Math.max(height, y - GROUP_GAP);
  }
  return { placed, boxes, width: cols.length * (NODE_W + COL_GAP) - COL_GAP, height };
}

/** "Contract §2.1" */
export function cite(data: GraphData, id: string): string {
  for (const lane of data.lanes) {
    const c = lane.clips.find((x) => x.id === id);
    if (c) return c.node === "answer" ? "the answer" : c.node === "absent" ? lane.name : `${lane.name} ${sec(c)}`.trim();
  }
  return id;
}
