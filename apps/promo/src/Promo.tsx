import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, Sequence, staticFile, useCurrentFrame } from "remotion";
import { Audio } from "@remotion/media";
import {
  ANSWER_IN, CAMERA, CAPTIONS, DURATION, ENTER, HL, KEY_FRAMES, PAPER_W, QUESTION, SFX, TRACE_POINTS, TRACE_TIMING, W,
} from "./timeline";
import { dark, DOC_FONT, light, UI_FONT } from "./tokens";

export type PromoProps = { bgm: boolean };

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const easeMove = Easing.bezier(0.65, 0, 0.35, 1);
const easeOut = Easing.bezier(0.16, 1, 0.3, 1);
const ramp = (f: number, a: number, b: number, ease = easeOut) => interpolate(f, [a, b], [0, 1], { ...clamp, easing: ease });

// ---------------------------------------------------------------- camera
function camera(frame: number) {
  let i = 0;
  while (i < CAMERA.length - 2 && frame >= CAMERA[i + 1][0]) i++;
  const [f0, x0, y0, z0, r0] = CAMERA[i];
  const [f1, x1, y1, z1, r1] = CAMERA[i + 1];
  const p = easeMove(Math.min(1, Math.max(0, (frame - f0) / (f1 - f0))));
  // zoom interpolated in log space so push-ins feel linear to the eye
  const z = Math.exp(Math.log(z0) + (Math.log(z1) - Math.log(z0)) * p);
  return { x: x0 + (x1 - x0) * p, y: y0 + (y1 - y0) * p, z, r: r0 + (r1 - r0) * p };
}

// ---------------------------------------------------------------- paper documents
type Para = { top: number; size: number; bold?: boolean; text: string; hl?: string; hlAt?: number; strikeAt?: number; tone?: "bad" };
const Paper: React.FC<{ x: number; y: number; rot: number; h: number; label: string; title: string; paras: Para[] }> = ({ x, y, rot, h, label, title, paras }) => {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: "absolute", left: x, top: y, width: PAPER_W, height: h, rotate: `${rot}deg`, background: light.surface,
      borderRadius: 6, boxShadow: "0 40px 90px rgba(0,0,0,.55), 0 2px 0 rgba(255,255,255,.4) inset", color: light.text }}>
      <div style={{ position: "absolute", left: 64, top: 50, font: `600 14px ${UI_FONT}`, letterSpacing: "0.16em", color: light.muted }}>{label}</div>
      <div style={{ position: "absolute", left: 64, right: 64, top: 80, font: `700 34px/1.2 ${DOC_FONT}` }}>{title}</div>
      {paras.map((p, i) => {
        const parts = p.hl ? p.text.split(p.hl) : [p.text];
        const hp = p.hlAt !== undefined ? ramp(frame, p.hlAt, p.hlAt + 22, Easing.bezier(0.33, 0, 0.2, 1)) : 0;
        const sp = p.strikeAt !== undefined ? ramp(frame, p.strikeAt, p.strikeAt + 20) : 0;
        const markCol = p.tone === "bad" ? "#fecaca" : light.mark;
        return (
          <div key={i} style={{ position: "absolute", left: 64, right: 64, top: p.top, font: `${p.bold ? 700 : 400} ${p.size}px/1.45 ${DOC_FONT}`,
            color: p.size < 19 ? light.muted : light.text }}>
            {parts[0]}
            {p.hl && (
              <span style={{
                backgroundImage: `linear-gradient(transparent 52%, ${light.bad} 52%, ${light.bad} 58%, transparent 58%), linear-gradient(${markCol}, ${markCol})`,
                backgroundRepeat: "no-repeat", backgroundSize: `${sp * 100}% 100%, ${hp * 100}% 100%`, borderRadius: 3,
                boxShadow: hp > 0.98 ? `0 0 0 2px ${p.tone === "bad" ? light.bad : light.warn}` : undefined,
              }}>{p.hl}</span>
            )}
            {parts[1]}
          </div>
        );
      })}
    </div>
  );
};

const Papers: React.FC = () => (
  <>
    <Paper {...W.msa} h={1040} label="CONTRACT · v1.0" title="Master Services Agreement" paras={[
      { top: 140, size: 17, text: "This Master Services Agreement (the “Agreement”) is entered into on January 10, 2026 between Halden Freight Co. (the “Customer”) and Corvane Software Ltd. (the “Vendor”)." },
      { top: 262, size: 22, bold: true, text: "2. Delivery" },
      { top: 304, size: 24, text: "2.1 The Vendor shall deliver the Phase 1 System no later than March 31, 2026.", hl: "no later than March 31, 2026.", hlAt: HL.msaDate, strikeAt: HL.strike },
      { top: 400, size: 19, text: "2.2 The Vendor shall provide weekly written progress reports to the Customer until Acceptance." },
      { top: 494, size: 22, bold: true, text: "3. Fees and Payment" },
      { top: 536, size: 19, text: "3.1 The Customer shall pay the Vendor a fixed fee of GBP 120,000 for the Phase 1 System." },
      { top: 604, size: 19, text: "3.2 The Customer shall pay each undisputed invoice within 30 days of receipt." },
      { top: 680, size: 22, bold: true, text: "4. Service Levels" },
      { top: 722, size: 19, text: "4.1 The Vendor shall ensure the Phase 1 System is available 99.5% of the time in each calendar month, excluding scheduled maintenance." },
      { top: 836, size: 22, bold: true, text: "5. Security and Data" },
      { top: 878, size: 19, text: "5.2 The Vendor shall not transfer Customer data outside the United Kingdom without the Customer’s prior written consent." },
    ]} />
    <Paper {...W.amend} h={980} label="AMENDMENT · v1.0" title="Amendment No. 1" paras={[
      { top: 140, size: 17, text: "This Amendment No. 1 is made on February 20, 2026 and amends the Master Services Agreement dated January 10, 2026." },
      { top: 240, size: 22, bold: true, text: "1. Amendments" },
      { top: 282, size: 24, text: "1.1 Clause 2.1 of the Agreement is deleted and replaced with: “The Vendor shall deliver the Phase 1 System no later than May 15, 2026.”", hl: "no later than May 15, 2026.", hlAt: HL.amendDate },
      { top: 440, size: 19, text: "1.2 Clause 3.2 of the Agreement is deleted and replaced with: “The Customer shall pay each undisputed invoice within 45 days of receipt.”" },
      { top: 560, size: 19, text: "1.3 Clause 5.3 of the Agreement is deleted and replaced with: “The Vendor shall notify the Customer of any personal data breach within 72 hours of becoming aware of it.”" },
      { top: 700, size: 22, bold: true, text: "2. Fees" },
      { top: 742, size: 19, text: "2.1 In consideration of the revised delivery date, the Vendor shall reduce the fixed fee in clause 3.1 to GBP 110,000." },
      { top: 846, size: 22, bold: true, text: "3. General" },
      { top: 888, size: 19, text: "3.1 Except as amended by this Amendment, the Agreement remains in full force and effect." },
    ]} />
    <Paper {...W.delivery} h={660} label="EVIDENCE · v1.0" title="Phase 1 Delivery and Acceptance Record" paras={[
      { top: 206, size: 22, bold: true, text: "1. Delivery" },
      { top: 248, size: 24, text: "1.1 The Vendor delivered the Phase 1 System on May 22, 2026.", hl: "on May 22, 2026.", hlAt: HL.deliveryDate, tone: "bad" },
      { top: 350, size: 19, text: "1.2 The Customer issued written Acceptance of the Phase 1 System on June 5, 2026." },
      { top: 450, size: 22, bold: true, text: "2. Reporting" },
      { top: 492, size: 19, text: "2.1 Weekly written progress reports were received from the Vendor from January 2026 until Acceptance, except for the weeks of March 9 and March 16, 2026." },
    ]} />
    <Paper {...W.audit} h={900} label="AUDIT REPORT · v1.0" title="Vendor Security Audit Report" paras={[
      { top: 140, size: 17, text: "Prepared for Halden Freight Co. Audit period: April 1, 2026 to June 30, 2026." },
      { top: 220, size: 22, bold: true, text: "2. Findings" },
      { top: 262, size: 19, text: "2.1 Encryption at rest: Customer data is encrypted at rest using AES-256. Control implemented and operating effectively." },
      { top: 370, size: 19, text: "2.2 Data location: All Customer data is hosted in the vendor’s Dublin, Ireland data centre." },
      { top: 450, size: 19, text: "2.3 Incident notification: The Vendor’s incident response procedure requires customer notification within 72 hours of confirming a breach." },
      { top: 560, size: 19, text: "2.4 Administrative access: Multi-factor authentication is enforced for administrative access to production systems. However, two shared break-glass accounts were found without multi-factor authentication." },
      { top: 724, size: 19, text: "2.5 Availability: Measured availability for May 2026 was 99.1%." },
    ]} />
  </>
);

// ---------------------------------------------------------------- real UI screenshots
const Shot: React.FC<{ src: string; x: number; y: number; w: number; h: number; full?: number; appear?: number; reveal?: "fade" | "wipe"; children?: React.ReactNode }> = ({
  src, x, y, w, h, full, appear, reveal = "fade", children,
}) => {
  const frame = useCurrentFrame();
  const p = appear === undefined ? 1 : ramp(frame, appear, appear + 24);
  const cropped = full !== undefined && full > h;
  if (reveal === "wipe" && p <= 0) return null;
  return (
    <div style={{ position: "absolute", left: x, top: y, width: w, height: reveal === "wipe" ? h * p : h, overflow: "hidden", borderRadius: 8,
      opacity: reveal === "fade" ? p : 1, translate: reveal === "fade" ? `0 ${(1 - p) * 40}px` : undefined,
      boxShadow: "0 30px 80px rgba(0,0,0,.6), 0 0 0 1px rgba(143,179,255,.08)", background: dark.surface }}>
      <Img src={staticFile(`shots/${src}.png`)} style={{ width: w, height: full ?? h, display: "block" }} />
      {cropped && <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 56, background: `linear-gradient(transparent, ${dark.surface})` }} />}
      {children}
    </div>
  );
};

const Badge: React.FC<{ tone: "bad" | "info"; size: number; children: React.ReactNode }> = ({ tone, size, children }) => (
  <span style={{ display: "inline-flex", alignItems: "center", gap: size * 0.35, padding: `${size * 0.12}px ${size * 0.5}px`, borderRadius: 999,
    background: tone === "bad" ? dark.badBg : dark.infoBg, color: tone === "bad" ? dark.bad : dark.info, font: `700 ${size}px ${UI_FONT}`,
    whiteSpace: "nowrap", border: `1px solid ${tone === "bad" ? "rgba(252,165,165,.35)" : "rgba(147,197,253,.3)"}` }}>{children}</span>
);

const Wordmark: React.FC = () => {
  const frame = useCurrentFrame();
  const p = ramp(frame, HL.reveal - 6, HL.reveal + 26);
  return (
    <div style={{ position: "absolute", left: W.wordmark.x - 1200, width: 2400, top: W.wordmark.y - 150, textAlign: "center", color: dark.text }}>
      <div style={{ font: `700 150px ${UI_FONT}`, letterSpacing: `${(1 - p) * 0.25 - 0.02}em`, opacity: p, filter: `blur(${(1 - p) * 18}px)` }}>ClaimTrace</div>
      <div style={{ font: `500 34px ${UI_FONT}`, color: dark.muted, marginTop: 4, opacity: ramp(frame, HL.reveal + 14, HL.reveal + 40) }}>
        Map commitments. Ask questions. Verify every answer against the exact source.
      </div>
    </div>
  );
};

const Register: React.FC = () => {
  const frame = useCurrentFrame();
  const a = ramp(frame, 600, 630);
  const chip = ramp(frame, HL.chip, HL.chip + 18);
  return (
    <>
      <div style={{ position: "absolute", left: W.replaced.x, top: W.replaced.y - 64, font: `700 26px ${UI_FONT}`, letterSpacing: "0.14em", color: dark.muted, whiteSpace: "nowrap", opacity: a }}>
        COMMITMENT REGISTER · MASTER SERVICES AGREEMENT
      </div>
      <Shot src="register-replaced" {...W.replaced} full={490} appear={596} />
      <Shot src="register-current" {...W.current} full={432} appear={612} />
      <svg style={{ position: "absolute", left: W.replaced.x + W.replaced.w, top: W.current.y + 90, overflow: "visible", opacity: a }} width={94} height={40}>
        <path d="M14 20 H74 M60 8 L76 20 L60 32" stroke={dark.accent} strokeWidth={5} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div style={{ position: "absolute", left: W.replaced.x, top: W.replaced.y + W.replaced.h + 40, opacity: chip, translate: `0 ${(1 - chip) * 16}px` }}>
        <Badge tone="info" size={30}>Changed by the amendment (§2.1). Date differs: 31 Mar 2026 vs 15 May 2026.</Badge>
      </div>
      <Shot src="source-mark" {...W.source} appear={700}>
        <div style={{ position: "absolute", left: 10, top: 336, width: 434, height: 40, borderRadius: 4,
          boxShadow: `0 0 ${30 * ramp(frame, HL.sourceMark, HL.sourceMark + 16)}px ${12 * ramp(frame, HL.sourceMark, HL.sourceMark + 16)}px rgba(252,211,77,.28)` }} />
      </Shot>
      <div style={{ position: "absolute", left: W.source.x, top: W.source.y - 64, font: `700 26px ${UI_FONT}`, letterSpacing: "0.14em", color: dark.muted, whiteSpace: "nowrap", opacity: ramp(frame, 704, 730) }}>
        THE EXACT SOURCE TEXT
      </div>
    </>
  );
};

const AskBox: React.FC = () => {
  const frame = useCurrentFrame();
  // input box inside ask-form-empty.png (CSS px, from scripts/capture.cjs layout.json)
  const inp = { x: 17, y: 45, w: 1044, h: 44 };
  const typed = KEY_FRAMES.filter((k) => frame >= k).length;
  const text = QUESTION.slice(0, typed);
  const focused = frame >= KEY_FRAMES[0] - 12;
  const caretOn = Math.floor(frame / 15) % 2 === 0 || (typed > 0 && typed < QUESTION.length);
  const press = interpolate(frame, [ENTER, ENTER + 3, ENTER + 12], [0, 1, 0], clamp);
  return (
    <Shot src="ask-form-empty" {...W.ask} appear={790}>
      {focused && (
        <>
          <div style={{ position: "absolute", left: inp.x - 4, top: inp.y - 4, width: inp.w + 8, height: inp.h + 8, borderRadius: 11, border: `3px solid ${dark.focus}` }} />
          <div style={{ position: "absolute", left: inp.x + 1, top: inp.y + 1, width: inp.w - 2, height: inp.h - 2, borderRadius: 7, background: dark.surface,
            font: `400 16px/42px ${UI_FONT}`, color: dark.text, paddingLeft: 12, whiteSpace: "pre" }}>
            {text}
            {frame < ENTER && <span style={{ display: "inline-block", width: 2, height: 20, marginLeft: 1, translate: "0 4px", background: caretOn ? dark.text : "transparent" }} />}
          </div>
        </>
      )}
      {typed >= 3 && (
        <div style={{ position: "absolute", left: inp.x + inp.w + 12, top: inp.y, width: 1152 - 17 - (inp.x + inp.w + 12), height: inp.h, borderRadius: 8,
          background: dark.accent, color: dark.accentText, font: `400 16px/44px ${UI_FONT}`, textAlign: "center",
          boxShadow: `0 0 0 ${press * 6}px rgba(143,179,255,${0.35 * press})`, scale: `${1 - press * 0.05}` }}>Ask</div>
      )}
    </Shot>
  );
};

const Answer: React.FC = () => {
  const frame = useCurrentFrame();
  const quotes = [
    { y: 227, col: dark.accent },
    { y: 315, col: dark.muted },
    { y: 403, col: dark.bad },
  ];
  return (
    <Shot src="answer-top" {...W.answer} appear={ANSWER_IN} reveal="wipe">
      {quotes.map((q, i) => {
        const p = ramp(frame, HL.quotes[i], HL.quotes[i] + 16);
        return (
          <div key={i} style={{ position: "absolute", left: 17, top: q.y, width: 1118, height: 40, borderRadius: 4,
            border: `2px solid ${q.col}`, opacity: p, boxShadow: `0 0 ${24 * p}px ${q.col}55`,
            clipPath: `inset(0 ${100 - p * 100}% 0 0)` }} />
        );
      })}
    </Shot>
  );
};

const Conflict: React.FC<{ src: string; box: { x: number; y: number; w: number; h: number }; at: number; big: string; small: string }> = ({ src, box, at, big, small }) => {
  const frame = useCurrentFrame();
  const appear = at - 50;
  const p = ramp(frame, at, at + 14, Easing.bezier(0.2, 1.6, 0.4, 1));
  const flash = interpolate(frame, [at, at + 4, at + 30], [0, 1, 0], clamp);
  return (
    <>
      <Shot src={src} {...box} full={542} appear={appear}>
        <div style={{ position: "absolute", inset: 0, borderRadius: 8, boxShadow: `inset 0 0 0 ${3 * flash}px ${dark.bad}, inset 0 0 ${80 * flash}px rgba(252,165,165,.25)` }} />
      </Shot>
      <div style={{ position: "absolute", left: box.x, top: box.y - 118, whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: 22, opacity: ramp(frame, at - 2, at + 8),
        scale: `${0.85 + 0.15 * p}`, transformOrigin: "left center" }}>
        <Badge tone="bad" size={48}>✕ {big}</Badge>
        <span style={{ font: `500 28px ${UI_FONT}`, color: dark.muted }}>{small}</span>
      </div>
    </>
  );
};

const Title: React.FC = () => {
  const frame = useCurrentFrame();
  const a = ramp(frame, HL.title - 22, HL.title + 10);
  const mk = ramp(frame, HL.title + 4, HL.title + 26, Easing.bezier(0.33, 0, 0.2, 1));
  const b = ramp(frame, HL.title + 24, HL.title + 50);
  const c = ramp(frame, HL.title + 40, HL.title + 66);
  return (
    <div style={{ position: "absolute", left: W.title.x - 1000, width: 2000, top: W.title.y - 150, textAlign: "center", color: dark.text }}>
      <div style={{ font: `700 112px ${UI_FONT}`, letterSpacing: "-0.02em", opacity: a, translate: `0 ${(1 - a) * 30}px` }}>
        Every answer is{" "}
        <span style={{ backgroundImage: `linear-gradient(${dark.mark}, ${dark.mark})`, backgroundRepeat: "no-repeat", backgroundSize: `${mk * 100}% 100%`,
          borderRadius: 6, padding: "0 10px", boxShadow: mk > 0.98 ? `0 0 0 3px ${dark.warn}` : undefined }}>a quote.</span>
      </div>
      <div style={{ font: `500 40px ${UI_FONT}`, color: dark.muted, marginTop: 34, opacity: b }}>ClaimTrace · open source · local-first</div>
      <div style={{ font: `600 46px ${UI_FONT}`, color: dark.accent, marginTop: 22, opacity: c }}>github.com/glowstonesq1/claimtrace</div>
      <div style={{ font: `400 22px ${UI_FONT}`, color: dark.muted, marginTop: 40, opacity: c * 0.8 }}>Sample documents shown are fictional. Not legal advice.</div>
    </div>
  );
};

// ---------------------------------------------------------------- trace line
function seg(i: number) {
  const P = TRACE_POINTS;
  const p0 = P[Math.max(0, i - 1)], p1 = P[i], p2 = P[i + 1], p3 = P[Math.min(P.length - 1, i + 2)];
  const c1: [number, number] = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
  const c2: [number, number] = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
  return { p1, c1, c2, p2 };
}
function bez(s: ReturnType<typeof seg>, t: number): [number, number] {
  const u = 1 - t;
  const f = (k: 0 | 1) => u * u * u * s.p1[k] + 3 * u * u * t * s.c1[k] + 3 * u * t * t * s.c2[k] + t * t * t * s.p2[k];
  return [f(0), f(1)];
}
const Trace: React.FC = () => {
  const frame = useCurrentFrame();
  let head: [number, number] | null = null;
  const paths = TRACE_TIMING.map(([a, b], i) => {
    const p = ramp(frame, a, b, Easing.bezier(0.45, 0, 0.25, 1));
    const s = seg(i);
    if (p > 0 && p < 1) head = bez(s, p);
    const d = `M${s.p1[0]} ${s.p1[1]} C${s.c1[0]} ${s.c1[1]} ${s.c2[0]} ${s.c2[1]} ${s.p2[0]} ${s.p2[1]}`;
    return p <= 0 ? null : (
      <g key={i}>
        <path d={d} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - p} stroke={dark.accent} strokeOpacity={0.16} strokeWidth={18} fill="none" strokeLinecap="round" />
        <path d={d} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - p} stroke={dark.accent} strokeOpacity={0.9} strokeWidth={4} fill="none" strokeLinecap="round" />
      </g>
    );
  });
  const h = head as [number, number] | null;
  return (
    <svg style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }} width={1} height={1}>
      <defs>
        <radialGradient id="glow"><stop offset="0" stopColor="#ffffff" /><stop offset="0.25" stopColor={dark.accent} stopOpacity={0.9} /><stop offset="1" stopColor={dark.accent} stopOpacity={0} /></radialGradient>
      </defs>
      {paths}
      {h && <circle cx={h[0]} cy={h[1]} r={34} fill="url(#glow)" />}
    </svg>
  );
};

// ---------------------------------------------------------------- captions (screen space)
const Captions: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <>
      {CAPTIONS.map((c) => {
        if (frame < c.from - 1 || frame > c.to + 1) return null;
        const a = ramp(frame, c.from, c.from + 14) * (1 - ramp(frame, c.to - 12, c.to, Easing.in(Easing.cubic)));
        const [pre, acc] = c.accent ? [c.text.slice(0, c.text.length - c.accent.length), c.accent] : [c.text, ""];
        return (
          <div key={c.from} style={{ position: "absolute", left: 120, bottom: 96, opacity: a, translate: `0 ${(1 - a) * 18}px`,
            background: "rgba(23,26,33,.95)", border: `1px solid ${dark.border}`, borderRadius: 8, padding: "18px 30px",
            font: `600 46px ${UI_FONT}`, color: dark.text, letterSpacing: "-0.01em", boxShadow: "0 20px 60px rgba(0,0,0,.5)" }}>
            {pre}<span style={{ color: dark.accent }}>{acc}</span>
          </div>
        );
      })}
    </>
  );
};

// ---------------------------------------------------------------- composition
export const Promo: React.FC<PromoProps> = ({ bgm }) => {
  const frame = useCurrentFrame();
  const c = camera(frame);
  const fadeIn = ramp(frame, 0, 24, Easing.linear);
  return (
    <AbsoluteFill style={{ background: dark.bg, fontFamily: UI_FONT, overflow: "hidden" }}>
      {/* parallax dot grid (moves slower than the world for depth) */}
      <AbsoluteFill style={{
        backgroundImage: `radial-gradient(circle, rgba(168,176,189,.16) 1.4px, transparent 1.6px)`,
        backgroundSize: `${44 * Math.sqrt(c.z)}px ${44 * Math.sqrt(c.z)}px`,
        backgroundPosition: `${-c.x * c.z * 0.55}px ${-c.y * c.z * 0.55}px`,
      }} />
      <div style={{ position: "absolute", left: 0, top: 0, transformOrigin: "0 0",
        transform: `translate(960px, 540px) rotate(${c.r}deg) scale(${c.z}) translate(${-c.x}px, ${-c.y}px)` }}>
        <Trace />
        <Papers />
        <Wordmark />
        <Shot src="library" {...W.library} appear={HL.reveal + 6} />
        <Register />
        <AskBox />
        <Answer />
        <Conflict src="vdel-late" box={W.card1} at={HL.impacts[0]} big="7 days late" small="Delivered 22 May · amended deadline 15 May" />
        <Conflict src="vaud-location" box={W.card2} at={HL.impacts[1]} big="United Kingdom ≠ Ireland" small="Contract §5.2 vs audit report §2.2" />
        <Conflict src="vaud-availability" box={W.card3} at={HL.impacts[2]} big="99.1% < 99.5%" small="Measured availability below the commitment" />
        <Title />
      </div>
      {/* vignette */}
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,.55) 100%)" }} />
      <Captions />
      <AbsoluteFill style={{ background: "#000", opacity: 1 - fadeIn }} />

      {bgm && <Audio src={staticFile("audio/bed.wav")} volume={0.42} />}
      {SFX.map((s, i) => (
        <Sequence key={i} from={s.at} durationInFrames={Math.min(240, DURATION - s.at)} layout="none" name={`sfx ${s.src} @${s.at}`}>
          <Audio src={staticFile(`audio/${s.src}.wav`)} volume={s.volume} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
