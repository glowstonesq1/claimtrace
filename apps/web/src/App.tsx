import { useEffect, useState } from "react";
import { Ask, Verify } from "./AskVerify";
import { DocumentView } from "./DocumentView";
import { Library } from "./Library";

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
  const hash = useHash();
  const [path, query] = hash.slice(1).split("?");
  const params = new URLSearchParams(query ?? "");
  const go = (h: string) => { window.location.hash = h; };
  useEffect(() => { document.getElementById("main")?.focus(); }, [path]);
  const section = path.startsWith("/doc/") ? "doc" : path.startsWith("/ask") ? "ask" : path.startsWith("/verify") ? "verify" : "home";
  useEffect(() => {
    document.title = { home: "Documents", doc: "Document", ask: "Ask", verify: "Check documents" }[section] + " · ClaimTrace";
  }, [section]);
  const link = (h: string, label: string, key: string) =>
    <a href={h} aria-current={section === key ? "page" : undefined}>{label}</a>;
  return (
    <>
      <a href="#main" className="skip" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>Skip to content</a>
      <header className="top">
        <span className="brand">ClaimTrace</span>
        <nav className="main" aria-label="Main">
          {link("#/", "Documents", "home")}{link("#/ask", "Ask", "ask")}{link("#/verify", "Check documents", "verify")}
        </nav>
      </header>
      <div className="banner" role="note">ClaimTrace helps you read documents. It is <strong>not legal advice</strong> and
        only knows what is in the documents you upload. Always check the quoted source.</div>
      <main id="main" tabIndex={-1}>
        {section === "home" && <Library go={go} />}
        {section === "doc" && <DocumentView key={path} id={path.split("/")[2]} />}
        {section === "ask" && <Ask />}
        {section === "verify" && <Verify runId={params.get("run") ?? undefined} />}
      </main>
      <footer>ClaimTrace 0.1 · runs on your computer · no tracking · <a href="/docs">API</a></footer>
    </>
  );
}
