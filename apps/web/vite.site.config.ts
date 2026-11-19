// The site's map script: src/flow/site.tsx with React and React Flow, as one self-hosted file plus its
// stylesheet (the site's policy allows scripts and styles from its own origin only). Built output is
// committed (apps/site/vendor/flow) so the site needs no build step; CI rebuilds it and fails on a diff.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  publicDir: "src/flow/public", // THIRD_PARTY_LICENSES.txt, copied beside the bundle
  build: {
    outDir: "../site/vendor/flow",
    emptyOutDir: true,
    sourcemap: false,
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        banner: "/*! ClaimTrace evidence map (apps/web/src/flow, Apache-2.0). Bundles: React and React DOM (MIT, Meta " +
          "Platforms), @xyflow/react and @xyflow/system (MIT, webkid GmbH), zustand (MIT, Paul Henschel), classcat (MIT, " +
          "Jorge Bucaran), d3-zoom, d3-selection, d3-drag, d3-interpolate, d3-transition, d3-color, d3-dispatch, " +
          "d3-timer (ISC, Mike Bostock) and d3-ease (BSD-3-Clause, Mike Bostock). Licence texts: THIRD_PARTY_LICENSES.txt beside this file. */",
      },
    },
    lib: { entry: "src/flow/site.tsx", formats: ["iife"], name: "ClaimTraceFlow", fileName: () => "flow.js"},
  },
});
