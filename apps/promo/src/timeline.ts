// Single source of truth for timing (frames @ 30 fps) and world layout (px in canvas space).
export const FPS = 30;
export const DURATION = 1620; // 54 s

// ---------- world layout -------------------------------------------------------------
export const PAPER_W = 760;
export const W = {
  msa: { x: 0, y: 0, rot: -0.8 },
  amend: { x: 880, y: 70, rot: 1.2 },
  delivery: { x: 1760, y: -30, rot: -1.0 },
  audit: { x: 2640, y: 60, rot: 1.6 },
  wordmark: { x: 1700, y: 1400 },
  library: { x: 1124, y: 1640, w: 1152, h: 284 },
  replaced: { x: 2560, y: 1520, w: 686, h: 295 },
  current: { x: 3340, y: 1548, w: 686, h: 240 },
  source: { x: 4140, y: 1340, w: 454, h: 720 },
  ask: { x: 2560, y: 2350, w: 1152, h: 182 },
  answer: { x: 2560, y: 2580, w: 1152, h: 509 },
  card1: { x: 1100, y: 3320, w: 1152, h: 362 },
  card2: { x: 2400, y: 3820, w: 1152, h: 362 },
  card3: { x: 1100, y: 4320, w: 1152, h: 362 },
  title: { x: 3900, y: 4720 },
};

// ---------- typing ---------------------------------------------------------------------
export const QUESTION = "Did the vendor promise delivery by March 31?";
export const TYPE_START = 856;
const hash = (i: number) => ((i * 2654435761) >>> 0) % 997;
export const KEY_FRAMES: number[] = (() => {
  const out: number[] = [];
  let f = TYPE_START;
  for (let i = 0; i < QUESTION.length; i++) {
    out.push(f);
    const ch = QUESTION[i];
    f += 2 + (hash(i + 3) % 2) + (ch === " " ? 1 : 0);
  }
  return out;
})();
export const TYPE_END = KEY_FRAMES[KEY_FRAMES.length - 1];
export const ENTER = TYPE_END + 10;
export const ANSWER_IN = ENTER + 8;

// ---------- camera keyframes: [frame, x, y, zoom, rotateDeg] -----------------------------
export type Key = [number, number, number, number, number];
export const CAMERA: Key[] = [
  [0, 380, 560, 0.6, -2],
  [130, 395, 340, 1.45, 0],
  [205, 1262, 430, 1.42, 0.8],
  [290, 1285, 424, 1.47, 0.8],
  [355, 2150, 250, 1.42, -0.5],
  [390, 2168, 246, 1.46, -0.5],
  [460, 1700, 500, 0.5, 0],
  [522, 1700, 560, 0.54, 0],
  [562, 1700, 1640, 0.95, 0],
  [600, 1705, 1650, 0.98, 0],
  [660, 3300, 1690, 0.9, 0],
  [700, 3330, 1695, 0.92, 0],
  [750, 4367, 1700, 1.38, 0],
  [790, 4360, 1705, 1.42, 0],
  [850, 3136, 2441, 1.3, 0],
  [ENTER, 3136, 2441, 1.45, 0],
  [ANSWER_IN + 50, 3136, 2835, 1.12, 0],
  [1110, 3140, 2850, 1.16, 0],
  [1165, 1676, 3440, 1.05, -0.6],
  [1185, 1690, 3437, 1.08, -0.6],
  [1235, 2976, 3940, 1.05, 0.6],
  [1255, 2990, 3937, 1.08, 0.6],
  [1305, 1676, 4440, 1.05, -0.4],
  [1350, 1690, 4437, 1.09, -0.4],
  [1410, 2700, 3800, 0.42, 0],
  [1470, 3900, 4720, 1.0, 0],
  [DURATION, 3900, 4724, 1.06, 0],
];

// ---------- story beats -------------------------------------------------------------------
export const HL = {
  msaDate: 92,
  amendDate: 218,
  deliveryDate: 362,
  strike: 420,
  reveal: 548,
  chip: 636,
  sourceMark: 756,
  quotes: [ANSWER_IN + 55, ANSWER_IN + 75, ANSWER_IN + 95],
  impacts: [1172, 1242, 1312],
  title: 1452,
};

export const CAPTIONS: { from: number; to: number; text: string; accent?: string }[] = [
  { from: 18, to: 124, text: "A contract sets a date.", accent: "a date." },
  { from: 148, to: 284, text: "An amendment quietly moves it.", accent: "quietly moves it." },
  { from: 300, to: 438, text: "The delivery record lands a week later.", accent: "a week later." },
  { from: 448, to: 528, text: "Three documents. Nobody lined them up.", accent: "Nobody lined them up." },
  { from: 604, to: 780, text: "ClaimTrace builds the commitment register.", accent: "commitment register." },
  { from: ANSWER_IN + 30, to: 1106, text: "Answers are built only from verified quotes.", accent: "verified quotes." },
  { from: 1118, to: 1342, text: "Then it checks documents against each other.", accent: "against each other." },
];

// ---------- the trace (accent line the camera follows) -------------------------------------
export const TRACE_POINTS: [number, number][] = [
  [655, 330], // MSA 2.1 highlight
  [1460, 470], // amendment 1.1 highlight
  [2300, 255], // delivery 1.1 highlight
  [2480, 1150], // waypoint right of the wordmark
  [2200, 1640], // library
  [2560, 1668], // replaced card
  [3340, 1668], // current card
  [4140, 1700], // source text
  [3136, 2350], // ask form
  [2560, 3000], // answer
  [1676, 3320], // card 1
  [2400, 4000], // card 2
  [2252, 4320], // card 3
  [3200, 4720], // title
];
export const TRACE_TIMING: [number, number][] = [
  [496, 512],
  [512, 528],
  [530, 548],
  [548, 566],
  [592, 632],
  [632, 656],
  [700, 742],
  [792, 846],
  [ANSWER_IN + 10, ANSWER_IN + 50],
  [1112, 1162],
  [1186, 1232],
  [1256, 1302],
  [1412, 1462],
];

// ---------- sound placements --------------------------------------------------------------
export const SFX: { src: string; at: number; volume: number }[] = [
  ...[126, 286, 386, 586, 696, 786, 1106, 1182, 1252].map((at) => ({ src: "whoosh", at, volume: 0.32 })),
  ...[1346, 1406].map((at) => ({ src: "whoosh2", at, volume: 0.38 })),
  { src: "mark", at: HL.msaDate, volume: 0.45 },
  { src: "mark", at: HL.amendDate, volume: 0.45 },
  { src: "mark", at: HL.deliveryDate, volume: 0.45 },
  { src: "mark", at: HL.chip, volume: 0.4 },
  { src: "mark", at: HL.sourceMark, volume: 0.4 },
  ...HL.quotes.map((at) => ({ src: "mark", at, volume: 0.36 })),
  { src: "riser", at: HL.reveal - 96, volume: 0.6 },
  { src: "hit", at: HL.reveal, volume: 0.95 },
  ...HL.impacts.map((at) => ({ src: "impact", at, volume: 0.9 })),
  ...KEY_FRAMES.map((at, i) => ({ src: `key${(hash(i + 11) % 3) + 1}`, at, volume: 0.6 })),
  { src: "enter", at: ENTER, volume: 0.75 },
  { src: "chime", at: HL.title, volume: 0.8 },
];
