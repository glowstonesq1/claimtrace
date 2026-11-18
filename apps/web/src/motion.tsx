// Tiny motion helpers. All animation is CSS (transform/opacity) in styles.css; this file only decides *when*.
import { useEffect, useState } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

export function reducedMotion(): boolean {
  try { return window.matchMedia(QUERY).matches; } catch { return false; }
}

/** Read a duration token (e.g. "--dur-exit") from :root so CSS stays the single source of timing. */
export function cssMs(token: string, fallback: number): number {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
    const n = parseFloat(v);
    return Number.isFinite(n) ? (v.endsWith("ms") ? n : n * 1000) : fallback;
  } catch { return fallback; }
}

/**
 * Route transition: when `key` changes, keep showing the old value during a short exit, then swap and enter.
 * Under reduced motion the swap is immediate.
 */
export function useRouteTransition<T>(value: T, key: string): { shown: T; phase: "enter" | "exit" } {
  const [state, setState] = useState({ shown: value, key, phase: "enter" as "enter" | "exit" });
  useEffect(() => {
    if (key === state.key) { if (value !== state.shown) setState((s) => ({ ...s, shown: value })); return; }
    if (reducedMotion()) { setState({ shown: value, key, phase: "enter" }); return; }
    setState((s) => ({ ...s, phase: "exit" }));
    const t = window.setTimeout(() => setState({ shown: value, key, phase: "enter" }), cssMs("--dur-exit", 140));
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, key]);
  return { shown: state.shown, phase: state.phase };
}

// ------------------------------------------------------------------ toast
type ToastItem = { id: number; text: string; leaving: boolean };
const listeners = new Set<(t: ToastItem[]) => void>();
let items: ToastItem[] = [];
let seq = 0;
const emit = () => listeners.forEach((l) => l(items));

/** Show a short confirmation for an effect the page does not otherwise make obvious (e.g. a saved review). */
export function toast(text: string, dwell = 4000) {
  const id = ++seq;
  items = [...items.slice(-2), { id, text, leaving: false }];
  emit();
  window.setTimeout(() => {
    items = items.map((t) => (t.id === id ? { ...t, leaving: true } : t)); emit();
    window.setTimeout(() => { items = items.filter((t) => t.id !== id); emit(); }, reducedMotion() ? 0 : cssMs("--dur-exit", 140));
  }, dwell);
}

/**
 * Visual-only: every toast repeats a message that is also written to a nearby role="status" region,
 * so the toaster is hidden from assistive tech to avoid announcing it twice.
 */
export function Toaster() {
  const [list, setList] = useState<ToastItem[]>(items);
  useEffect(() => { listeners.add(setList); return () => { listeners.delete(setList); }; }, []);
  return (
    <div className="toaster" aria-hidden="true">
      {list.map((t) => (
        <div key={t.id} className={`toast ${t.leaving ? "out" : "in"}`}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M3 8.5l3 3L13 5" /></svg>
          {t.text}
        </div>))}
    </div>
  );
}

// ------------------------------------------------------------------ skeleton
/** Placeholder shape for content that is on its way. The label is announced; the bars are decoration. */
export function Skeleton({ label, lines = ["w-30", "w-95", "w-80", "w-60"], card = true }: {
  label: string; lines?: string[]; card?: boolean }) {
  return (
    <div className={card ? "card" : undefined} aria-busy="true">
      {label && <span className="sr" role="status">{label}</span>}
      <div className="skeleton" aria-hidden="true">{lines.map((w, i) => <div key={i} className={`bar ${w}`} />)}</div>
    </div>
  );
}
