// The site's map script (built to apps/site/vendor/flow/flow.js by vite.site.config.ts):
//
//   ClaimTraceGraph.mount(el, data, options) -> { update(options), select(id), destroy() }
//
// `data` is the model claimtrace.browser.graph() builds; options are FlowOptions. A map rendered at build time
// (the home page: [data-map][data-graph-src]) is drawn without scripting; once its data loads, this replaces it.
import "@xyflow/react/dist/base.css";
import "./flow.css";
import { createRoot, type Root } from "react-dom/client";
import { EvidenceFlow, type FlowOptions } from "./EvidenceFlow";
import type { GraphData } from "./model";

function mount(host: HTMLElement, data: GraphData, options: FlowOptions = {}) {
  let opts: FlowOptions = { ...options };
  let root: Root | null = createRoot(host);
  const draw = () => root?.render(<EvidenceFlow data={data} options={opts} />);
  draw();
  return {
    update(next: FlowOptions) { opts = { ...opts, ...next }; draw(); },
    select(id: string) { opts = { ...opts, selected: id }; draw(); },
    destroy() { root?.unmount(); root = null; host.textContent = ""; },
  };
}

declare global { interface Window { ClaimTraceGraph: { mount: typeof mount } } }
window.ClaimTraceGraph = { mount };

for (const host of document.querySelectorAll<HTMLElement>("[data-map][data-graph-src]")) {
  const url = new URL(host.getAttribute("data-graph-src")!, document.baseURI);
  fetch(url)
    .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json() as Promise<GraphData>; })
    .then((data) => {
      const section = host.closest("section");
      section?.querySelectorAll<HTMLElement>("[data-map-fallback]").forEach((el) => { el.hidden = true; });
      const label = host.getAttribute("aria-labelledby");
      const slot = document.createElement("div");
      host.replaceWith(slot);
      mount(slot, data, {
        selected: host.getAttribute("data-graph-selected") || undefined,
        label: (label && document.getElementById(label)?.textContent) || undefined,
      });
    })
    .catch(() => { /* the map drawn at build time stays */ });
}
