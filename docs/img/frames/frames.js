// Frame definitions. Each crop is in CSS pixels of a capture taken at deviceScaleFactor 2 (raw/*.png).
// frame.html?f=<name> renders one frame; render.mjs screenshots each at deviceScaleFactor 2.
const FRAMES = {
  hero: { bare: true,
    panels: [{ src: 'raw/hero.png', crop: { x: 0, y: 0, w: 1280, h: 860 }, width: 1200 }] },
  map: {
    title: 'Every finding points back to a clause',
    note: ['The evidence map', 'Contract clause 2.1 selected: replaced by Amendment No. 1 §1.1.'],
    panels: [{ src: 'raw/map.png', crop: { x: 36, y: 226, w: 1208, h: 540 } }] },
  try: {
    title: 'Check a contract in your browser',
    note: ['The workbench at /try', 'The four samples loaded and checked. Nothing is uploaded.'],
    panels: [
      { src: 'raw/try-register.png', crop: { x: 36, y: 0, w: 1208, h: 700 }, width: 760 },
      { src: 'raw/try-check.png', crop: { x: 452, y: 56, w: 776, h: 640 }, width: 520, left: 548, top: 96 },
    ] },
  evidence: {
    title: 'The numbers, including the bad ones',
    note: ['The evidence ledger', 'Sealed test sets, 95% intervals, a keyword floor beside each number.'],
    panels: [{ src: 'raw/evidence-answers.png', crop: { x: 36, y: 132, w: 1208, h: 640 } }] },
};

const name = new URLSearchParams(location.search).get('f') || 'map';
const f = FRAMES[name];
const stage = document.getElementById('stage');
const frame = document.createElement('figure');
frame.className = 'frame' + (f.bare ? ' frame--bare' : '');
frame.style.margin = '0';
if (!f.bare) {
  frame.insertAdjacentHTML('beforeend', `<div class="sky"></div>
    <header class="head"><div><span class="wordmark"><svg><use href="#mark"/></svg>ClaimTrace</span><h1>${f.title}</h1></div>
    <p class="note"><b>${f.note[0]}</b>${f.note[1]}</p></header>`);
}
const wrap = document.createElement('div');
wrap.className = f.bare ? '' : 'bezels';
frame.appendChild(wrap);
let bottom = 0;
const inner = f.bare ? 1200 : 1200 - 2 * 56 - 2 * 10;
f.panels.forEach((p, i) => {
  const w = p.width ? (f.bare ? p.width : p.width - 20) : inner;
  const s = w / p.crop.w;
  const h = Math.round(p.crop.h * s);
  const bezel = document.createElement('div');
  bezel.className = f.bare ? '' : 'bezel' + (i > 0 ? ' bezel--front' : '');
  if (i > 0) { bezel.style.left = p.left + 'px'; bezel.style.top = p.top + 'px'; }
  if (p.width && !f.bare) bezel.style.width = p.width + 'px';
  const crop = document.createElement('div');
  crop.className = 'crop';
  crop.style.width = w + 'px';
  crop.style.height = h + 'px';
  const img = new Image();
  img.src = p.src;
  img.alt = '';
  img.onload = () => {
    img.style.width = (img.naturalWidth / 2) * s + 'px';
    img.style.left = -p.crop.x * s + 'px';
    img.style.top = -p.crop.y * s + 'px';
    img.dataset.ready = '1';
  };
  crop.appendChild(img);
  bezel.appendChild(crop);
  wrap.appendChild(bezel);
  bottom = Math.max(bottom, (i > 0 ? p.top : 0) + h + (f.bare ? 0 : 2 * 10));
});
// the glass runs off the bottom edge of the frame by BLEED pixels; the bare hero is cut exactly
const BLEED = 28;
wrap.style.height = bottom + 'px';
stage.appendChild(frame);
const head = frame.querySelector('.head');
frame.style.height = (head ? head.offsetHeight : 0) + bottom - (f.bare ? 0 : BLEED) + 'px';
