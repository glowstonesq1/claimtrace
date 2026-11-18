import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const api = "http://127.0.0.1:8000";
const proxied = ["/documents", "/ask", "/answers", "/verify", "/verifications", "/runs", "/findings",
  "/commitments", "/reviews", "/samples", "/health", "/privacy"];

export default defineConfig({
  plugins: [react()],
  build: { outDir: "../api/static", emptyOutDir: true, sourcemap: false },
  server: { proxy: Object.fromEntries(proxied.map((p) => [p, { target: api, changeOrigin: false }])) },
});
