import { useEffect, useState } from "react";
import { Ask, Verify } from "./AskVerify";
import { DocumentView } from "./DocumentView";
import { Library } from "./Library";
import { Toaster, useRouteTransition } from "./motion";

function useHash(): string {
  const [hash, setHash] = useState(window.location.hash || "#/");
  useEffect(() => {
    const on = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

export function App() {
  const liveHash = useHash();
  // The view swaps after a short exit; the nav reflects the destination at once.
  const { shown: hash, phase } = useRouteTransition(liveHash, liveHash.slice(1).split("?")[0]);
  const [path, query] = hash.slice(1).split("?");
  const livePath = liveHash.slice(1).split("?")[0];
  const params = new URLSearchParams(query ?? "");
  const go = (h: string) => { window.location.hash = h; };
  useEffect(() => { document.getElementById("main")?.focus(); }, [path]);
  const sectionOf = (p: string) => p.startsWith("/doc/") ? "doc" : p.startsWith("/ask") ? "ask" : p.startsWith("/verify") ? "verify" : "home";
  const navSection = sectionOf(livePath);
  const section = path.startsWith("/doc/") ? "doc" : path.startsWith("/ask") ? "ask" : path.startsWith("/verify") ? "verify" : "home";
  useEffect(() => {
    document.title = { home: "Documents", doc: "Document", ask: "Ask", verify: "Check documents" }[section] + " · ClaimTrace";
  }, [section]);
  const link = (h: string, label: string, key: string) =>
    <a href={h} aria-current={navSection === key ? "page" : undefined}>{label}</a>;
  return (
    <>
      <a href="#main" className="skip" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>Skip to content</a>
      <header className="top">
        <span className="brand"><svg width="20" height="20" viewBox="0 0 16 16" aria-hidden="true"><rect width="16" height="16" rx="3"
          fill="currentColor" /><path d="M4 8.5l2.5 2.5L12 5" style={{ stroke: "var(--accent-ink)" }} strokeWidth="2" fill="none" /></svg>ClaimTrace</span>
        <nav className="main" aria-label="Main">
          {link("#/", "Documents", "home")}{link("#/ask", "Ask", "ask")}{link("#/verify", "Check documents", "verify")}
        </nav>
      </header>
      <div className="banner" role="note">ClaimTrace helps you read documents. It is <strong>not legal advice</strong> and
        only knows what is in the documents you upload. Always check the quoted source.</div>
      <main id="main" tabIndex={-1}>
        <div key={path} className={`route ${phase}`}>
          {section === "home" && <Library go={go} />}
          {section === "doc" && <DocumentView id={path.split("/")[2]} />}
          {section === "ask" && <Ask />}
          {section === "verify" && <Verify runId={params.get("run") ?? undefined} />}
        </div>
      </main>
      <footer><ul className="meta tight"><li>ClaimTrace 0.1</li><li>Runs on your computer</li>
        <li>No tracking</li><li><a href="/docs">API</a></li></ul></footer>
      <Toaster />
    </>
  );
}
