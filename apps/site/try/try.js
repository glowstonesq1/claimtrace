// Try page: the UI. The engine runs in engine-worker.mjs; this file never sends a document anywhere.
// Document text is untrusted: it is only ever inserted with textContent, never as HTML.

const $ = (id) => document.getElementById(id);
const MAX_BYTES = 10 * 1024 * 1024;
const ACCEPT = /\.(pdf|docx|txt|text|md|markdown)$/i;
const SAMPLE_QUESTIONS = [
  'Did the vendor promise delivery by March 31?',
  'How many days does the customer have to pay invoices?',
  'Is customer data kept in the UK?',
  'What is the liability cap?',
];

const LABEL = {
  type: { obligation: 'Must do', prohibition: 'Must not', entitlement: 'May', condition: 'Condition', deadline: 'Deadline',
    consequence: 'Consequence', service_level: 'Service level' },
  doc: { contract: 'Contract', amendment: 'Amendment', audit_report: 'Audit report', evidence: 'Record', report: 'Report',
    policy: 'Policy', sow: 'Statement of work', proposal: 'Proposal', other: 'Document' },
  answer: { stated: 'Found in the documents', implied: 'Implied, not stated outright', contradicted: 'The documents disagree',
    not_addressed: 'Not found in the documents', ambiguous: 'Unclear: more than one reading',
    needs_human_review: 'A person needs to check this' },
  verdict: { consistent: 'Consistent', contradicted: 'Contradicted', partially_supported: 'Partly supported',
    not_addressed: 'Not mentioned', ambiguous: 'Unclear', needs_human_review: 'Needs a person to check' },
  severity: { high: 'High', medium: 'Medium', low: 'Low', info: 'Note' },
  role: { supports: 'Supports', conflicts: 'Conflicts', context: 'Context', checked_not_supporting: 'Checked, does not support' },
  mode: { amendment: 'Amendment check', evidence: 'Evidence check', version: 'Version comparison', general: 'Comparison' },
};

const fmtDate = new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' });
const mb = (n) => (n / 1e6).toFixed(1);

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) {
    if (kid === undefined || kid === null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

// ---- engine -------------------------------------------------------------------------------------
const pending = new Map();
let nextId = 1;
let worker = null;
let started = 0;
let lastAnnounced = -1;

function startEngine() {
  started = performance.now();
  // A blob: worker inherits this page's Content-Security-Policy (connect-src 'self'), so the engine
  // cannot reach another origin. It only imports the real worker script from this site.
  const src = new URL('engine-worker.mjs', import.meta.url).href;
  const blob = new Blob([`import ${JSON.stringify(src)};\n`], { type: 'text/javascript' });
  try {
    worker = new Worker(URL.createObjectURL(blob), { type: 'module', name: 'claimtrace-engine' });
  } catch {
    engineFailed('This browser cannot run the engine (module workers are not supported).');
    return;
  }
  worker.onmessage = (e) => {
    const msg = e.data;
    if (msg.type === 'progress') return onProgress(msg);
    const p = pending.get(msg.id);
    if (!p) return;
    pending.delete(msg.id);
    msg.ok ? p.resolve(msg.result) : p.reject(Object.assign(new Error(msg.error.message), { code: msg.error.code }));
  };
  worker.onerror = () => engineFailed('The engine could not start in this browser.');
}

function request(op, args = {}, files = null) {
  return new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    const transfer = files ? files.map((f) => f.buffer) : [];
    worker.postMessage({ id, op, args, files }, transfer);
  });
}

function onProgress(m) {
  const status = $('engine-status');
  const bar = $('engine-progress');
  if (m.phase === 'download') {
    const pct = m.total ? Math.floor((m.loaded / m.total) * 100) : 0;
    bar.value = pct;
    status.textContent = `Loading the engine: ${mb(m.loaded)} of ${mb(m.total)} MB.`;
    const step = Math.floor(pct / 25);
    if (step !== lastAnnounced) {
      lastAnnounced = step;
      $('engine-live').textContent = `Loading the engine, ${pct} percent.`;
    }
  } else if (m.phase === 'start') {
    bar.value = 100;
    status.textContent = 'Starting the engine.';
  } else if (m.phase === 'ready') {
    bar.value = 100;
    const secs = ((performance.now() - started) / 1000).toFixed(1);
    const fromCache = m.transferred < m.total * 0.05;
    status.textContent = `Engine ready in ${secs} s.`;
    $('engine-note').textContent = fromCache
      ? `Loaded from your browser's copy (${mb(m.total)} MB). Nothing was downloaded this time.`
      : `Downloaded ${mb(m.transferred)} MB from this site. Your browser keeps a copy, so next time is faster.`;
    $('engine-live').textContent = 'Engine ready. You can add documents.';
    document.body.dataset.engine = 'ready';
    for (const id of ['load-samples', 'file-input']) $(id).disabled = false;
  } else if (m.phase === 'failed') {
    engineFailed('The engine could not start in this browser. Try a current version of Chrome, Edge, Firefox or Safari.');
  }
}

function engineFailed(text) {
  $('engine-status').textContent = text;
  $('engine-live').textContent = text;
  $('engine-progress').hidden = true;
  document.body.dataset.engine = 'failed';
}

// ---- state --------------------------------------------------------------------------------------
let register = null;
let samplesLoaded = false;
const docCache = new Map();

async function addFiles(fileList, label) {
  const status = $('add-status');
  const files = [];
  const refused = [];
  for (const f of fileList) {
    if (!ACCEPT.test(f.name)) refused.push(`${f.name}: only PDF, Word (.docx), text and Markdown files can be read.`);
    else if (f.size > MAX_BYTES) refused.push(`${f.name}: larger than 10 MB.`);
    else files.push({ name: f.name, buffer: await f.arrayBuffer() });
  }
  if (!files.length) {
    status.textContent = refused.join(' ') || 'No files chosen.';
    return;
  }
  setBusy(true);
  status.textContent = `Reading ${label}. This stays in this tab.`;
  try {
    register = await request('analyze', {}, files);
    docCache.clear();
    const problems = register.warnings.filter((w) => w.code !== 'note' && !w.document_id);
    const notes = [...refused, ...problems.map((w) => `${w.file}: ${w.message}`)];
    const n = register.added.length;
    status.textContent = `Read ${n} document${n === 1 ? '' : 's'}.` + (notes.length ? ` Not read: ${notes.join(' ')}` : '');
    render();
    $('register-title').focus();
  } catch (err) {
    status.textContent = `Something went wrong while reading: ${err.message}`;
  } finally {
    setBusy(false);
  }
}

async function loadSamples() {
  const names = await (await fetch('samples/index.json')).json();
  const files = [];
  for (const name of names) {
    const res = await fetch(`samples/${name}`);
    files.push(new File([await res.arrayBuffer()], name, { type: 'text/markdown' }));
  }
  samplesLoaded = true;
  await addFiles(files, 'the four sample documents');
}

function setBusy(busy) {
  for (const id of ['load-samples', 'file-input', 'ask-button', 'check-button', 'reset', 'export-json', 'export-md']) {
    const el = $(id);
    if (el) el.disabled = busy;
  }
  $('load-samples').setAttribute('aria-busy', busy ? 'true' : 'false');
}

// ---- rendering: documents and register ------------------------------------------------------------
function render() {
  const docs = register ? register.documents : [];
  const has = docs.length > 0;
  for (const id of ['register', 'ask', 'check', 'doc-tools']) $(id).hidden = !has;
  renderDocs(docs);
  if (!has) return;
  renderRegister();
  renderSuggestions();
  renderCheckOptions(docs);
}

function renderDocs(docs) {
  const titles = Object.fromEntries(docs.map((d) => [d.id, d.title]));
  $('doc-list').replaceChildren(...docs.map((d) => h('li', { class: 'doc' },
    h('span', { class: 'doc__title', text: d.title }),
    h('span', { class: 'doc__meta' },
      h('span', { text: LABEL.doc[d.type] || 'Document' }),
      d.amends_document_id ? h('span', { text: `amends ${titles[d.amends_document_id] || 'another document'}` }) : null,
      h('span', { text: d.filename || '' })),
    ...d.warnings.map((w) => h('p', { class: 'doc__warn', text: plainWarning(w) })))));
}

function plainWarning(w) {
  return w.replace(/^[A-Z]+: /, '');
}

function partyNames() {
  const names = {};
  for (const p of register.parties) if (p.alias && !names[p.alias]) names[p.alias] = p.name;
  return names;
}

function deadlineText(d) {
  if (!d || d.kind === 'none') return null;
  if (d.date) return `Due ${fmtDate.format(new Date(d.date + 'T00:00:00Z'))}`;
  if (d.kind === 'recurring' && d.raw) return d.raw.charAt(0).toUpperCase() + d.raw.slice(1);
  return d.raw ? `When: ${d.raw}` : null;
}

function renderRegister() {
  const items = register.commitments;
  const replaced = items.filter((c) => c.document_effect !== 'in_force').length;
  const flagged = items.filter((c) => c.needs_review).length;
  const { quotes, verified } = register.integrity;
  $('register-summary').textContent = [
    `${items.length} commitments from ${register.documents.length} documents.`,
    replaced ? `${replaced} replaced or removed by an amendment.` : '',
    flagged ? `${flagged} flagged for a person to check.` : '',
    verified === quotes ? 'Every quote matches its document exactly.' : `${quotes - verified} quotes could not be matched to their document.`,
  ].filter(Boolean).join(' ');

  const dl = register.deadlines.filter((d) => d.date);
  $('deadlines').replaceChildren(dl.length ? h('div', { class: 'deadlines__wrap' },
    h('h3', { class: 'sub', text: 'Dated deadlines' }),
    h('table', { class: 'table' },
      h('thead', {}, h('tr', {}, ['Date', 'Who', 'What', 'Where'].map((t) => h('th', { scope: 'col', text: t })))),
      h('tbody', {}, dl.map((d) => {
        const c = items.find((i) => i.id === d.commitment_id);
        return h('tr', { class: d.in_force ? null : 'is-replaced' },
          h('td', { class: 'num' }, fmtDate.format(new Date(d.date + 'T00:00:00Z')), d.in_force ? null : h('span', { class: 'tag', text: 'replaced' })),
          h('td', { text: d.party || 'No party named' }),
          h('td', { text: c ? c.action : '' }),
          h('td', { text: `${d.document}${d.section ? `, §${d.section}` : ''}` }));
      })))) : '');

  const names = partyNames();
  const groups = new Map();
  for (const c of items) {
    const key = c.obliging_party || 'No party named';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(c);
  }
  const ordered = [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
  $('parties').replaceChildren(...ordered.map(([party, list]) => h('section', { class: 'party', 'aria-label': party },
    h('h3', { class: 'party__head' }, party, names[party] ? h('span', { class: 'party__legal', text: names[party] }) : null,
      h('span', { class: 'party__count', text: `${list.length}` })),
    h('ol', { class: 'items' }, list.map(renderItem)))));
}

function renderItem(c) {
  const replaced = c.document_effect !== 'in_force';
  const q = c.quote || {};
  return h('li', { class: `item${replaced ? ' is-replaced' : ''}${c.needs_review ? ' is-flagged' : ''}`, 'data-id': c.id },
    h('p', { class: 'item__meta' },
      h('span', { class: 'item__sec', text: c.section ? `§${c.section}` : 'No clause number' }),
      h('span', { text: c.document }),
      h('span', { class: 'tag', text: LABEL.type[c.type] || c.type }),
      deadlineText(c.deadline) ? h('span', { text: deadlineText(c.deadline) }) : null),
    h('blockquote', { class: 'quote' }, h('p', { text: q.quote || c.text })),
    replaced ? h('p', { class: 'item__state' },
      h('strong', { text: c.document_effect === 'deleted' ? 'Removed by amendment.' : 'Replaced by amendment.' }), ' ',
      c.replaced_by.length
        ? c.replaced_by.map((r) => `Now: "${r.text}" (${r.document}${r.section ? `, §${r.section}` : ''})`).join(' ')
        : (c.caveats.find((cv) => /^(Replaced|Deleted|Changed) by /.test(cv)) || '')) : null,
    c.amends_section ? h('p', { class: 'item__state', text: `New wording from an amendment, for clause ${c.amends_section}.` }) : null,
    c.needs_review ? h('p', { class: 'item__flag' }, h('strong', { text: 'Check this.' }), ' ',
      c.review_reasons.join(' ') || 'The engine was not confident about this one.') : null,
    h('p', { class: 'item__foot' },
      verifiedTag(q.verified),
      showButton(q)));
}

function verifiedTag(ok) {
  return ok
    ? h('span', { class: 'check-ok', text: 'Quote matches the document' })
    : h('span', { class: 'check-bad', text: 'Quote could not be matched' });
}

function showButton(span) {
  if (!span || !span.document_id) return null;
  return h('button', { class: 'linkbtn', type: 'button', onclick: (e) => showInDocument(span, e.currentTarget) }, 'Show in document');
}

// ---- show in document ---------------------------------------------------------------------------
let viewerReturn = null;

async function showInDocument(span, trigger) {
  let doc = docCache.get(span.document_id);
  if (!doc) {
    doc = await request('document', { doc_id: span.document_id });
    docCache.set(span.document_id, doc);
  }
  const text = doc.text;
  const mark = h('mark', { class: 'hl', id: 'viewer-mark', text: text.slice(span.char_start, span.char_end) });
  $('viewer-title').textContent = doc.title;
  $('viewer-where').textContent = [span.section ? `Clause ${span.section}` : null, span.page ? `page ${span.page}` : null,
    'The quoted passage is highlighted.'].filter(Boolean).join(', ').replace(', The', '. The');
  $('viewer-text').replaceChildren(text.slice(0, span.char_start), mark, text.slice(span.char_end));
  viewerReturn = trigger;
  const dlg = $('viewer');
  dlg.showModal();
  $('viewer-close').focus();
  mark.scrollIntoView({ block: 'center' });
}

function closeViewer() {
  $('viewer').close();
}

// ---- ask ----------------------------------------------------------------------------------------
function renderSuggestions() {
  $('suggestions').replaceChildren(...(samplesLoaded ? SAMPLE_QUESTIONS : []).map((q) =>
    h('button', { class: 'chip', type: 'button', onclick: () => { $('question').value = q; ask(); } }, q)));
}

async function ask(event) {
  if (event) event.preventDefault();
  const question = $('question').value.trim();
  if (!question) return;
  setBusy(true);
  $('answer-status').textContent = 'Looking for an answer.';
  try {
    const a = await request('ask', { question });
    renderAnswer(a);
    const n = a.citations.length;
    const ok = a.citations.every((c) => c.verified);
    $('answer-status').textContent = `Answer: ${LABEL.answer[a.status] || a.status}. ${a.answer_text} ` +
      (n ? `${n} quote${n === 1 ? '' : 's'}${ok ? ', all matched to the documents' : ''}.` : '');
  } catch (err) {
    $('answer-status').textContent = `Could not answer: ${err.message}`;
  } finally {
    setBusy(false);
  }
}

function renderAnswer(a) {
  const card = h('article', { class: `answer__card is-${a.status}` },
    h('h3', { class: 'answer__status', text: LABEL.answer[a.status] || a.status }),
    h('p', { class: 'answer__question', text: `You asked: ${a.question}` }),
    h('p', { class: 'answer__text', text: a.answer_text }),
    a.citations.length ? h('ol', { class: 'cites' }, a.citations.map((c) => h('li', { class: `cite is-${c.role}` },
      h('p', { class: 'cite__role', text: LABEL.role[c.role] || c.role }),
      h('blockquote', { class: 'quote' }, h('p', { text: c.span.quote })),
      h('p', { class: 'cite__src', text: source(c.span) }),
      c.note ? h('p', { class: 'cite__note', text: c.note }) : null,
      h('p', { class: 'item__foot' }, verifiedTag(c.verified), showButton(c.span))))) : null,
    a.caveats.length ? h('ul', { class: 'notes', 'aria-label': 'Notes' }, a.caveats.map((t) => h('li', { text: t }))) : null);
  $('answer').replaceChildren(card);
}

function source(span) {
  return [span.document_title, span.document_version, span.section ? `§${span.section}` : null, span.page ? `page ${span.page}` : null]
    .filter(Boolean).join(', ');
}

// ---- check --------------------------------------------------------------------------------------
function renderCheckOptions(docs) {
  const base = $('base-doc');
  const other = $('other-doc');
  const prev = [base.value, other.value];
  const opts = () => docs.map((d) => h('option', { value: d.id, text: `${d.title} (${LABEL.doc[d.type] || 'Document'})` }));
  base.replaceChildren(...opts());
  other.replaceChildren(...opts());
  const contract = docs.find((d) => d.type === 'contract') || docs[0];
  base.value = docs.some((d) => d.id === prev[0]) ? prev[0] : contract.id;
  const second = docs.find((d) => d.id !== base.value);
  other.value = docs.some((d) => d.id === prev[1]) ? prev[1] : (second || contract).id;
}

async function check(event) {
  event.preventDefault();
  const base = $('base-doc').value;
  const other = $('other-doc').value;
  if (base === other) {
    $('check-status').textContent = 'Choose two different documents.';
    $('findings').replaceChildren(h('p', { class: 'panel__lede', text: 'Choose two different documents.' }));
    return;
  }
  setBusy(true);
  $('check-status').textContent = 'Checking.';
  try {
    const run = await request('verify', { base_id: base, other_id: other });
    renderFindings(run);
    const main = run.findings.filter((f) => !f.routine);
    $('check-status').textContent = `${LABEL.mode[run.mode] || 'Check'} done: ${main.length} finding${main.length === 1 ? '' : 's'}.`;
  } catch (err) {
    $('check-status').textContent = `Could not check: ${err.message}`;
  } finally {
    setBusy(false);
  }
}

function renderFindings(run) {
  const main = run.findings.filter((f) => !f.routine);
  const routine = run.findings.filter((f) => f.routine);
  const counts = Object.entries(run.summary).filter(([, n]) => n > 0)
    .map(([v, n]) => `${n} ${(LABEL.verdict[v] || v).toLowerCase()}`).join(', ');
  const finding = (f) => h('li', { class: `finding is-${f.severity} is-${f.verdict}` },
    h('p', { class: 'finding__head' },
      h('span', { class: 'sev', text: `${LABEL.severity[f.severity] || f.severity} severity` }),
      h('span', { class: 'finding__verdict', text: LABEL.verdict[f.verdict] || f.verdict })),
    h('blockquote', { class: 'quote' }, h('p', { text: f.subject_span ? f.subject_span.quote : f.subject_text })),
    f.subject_span ? h('p', { class: 'cite__src', text: source(f.subject_span) }) : null,
    f.subject_span ? h('p', { class: 'item__foot' }, verifiedTag(f.subject_span.verified), showButton(f.subject_span)) : null,
    h('p', { class: 'finding__why', text: f.explanation }),
    h('p', { class: 'finding__action' }, h('strong', { text: 'What to do: ' }), f.recommended_action),
    ...[...f.conflicting.map((s) => ['Conflicting text', s]), ...f.supporting.map((s) => ['Matching text', s])].map(([role, s]) =>
      h('div', { class: 'finding__other' },
        h('p', { class: 'cite__role', text: role }),
        h('blockquote', { class: 'quote' }, h('p', { text: s.quote })),
        h('p', { class: 'cite__src', text: source(s) }),
        h('p', { class: 'item__foot' }, verifiedTag(s.verified), showButton(s)))),
    null);
  $('findings').replaceChildren(
    h('h3', { class: 'sub', text: `${LABEL.mode[run.mode] || 'Check'}: ${run.base_document} against ${run.other_document}` }),
    h('p', { class: 'panel__lede', text: counts ? `Found ${counts}.` : 'Nothing to compare.' }),
    main.length ? h('ol', { class: 'findings__list' }, main.map(finding))
      : h('p', { class: 'panel__lede', text: 'No differences found. That is not proof the documents agree on everything; it checks dates, amounts, percentages, durations, places and obligation strength.' }),
    routine.length ? h('details', { class: 'routine' },
      h('summary', { text: run.mode === 'amendment'
        ? `${routine.length} clauses the amendment does not touch`
        : `${routine.length} commitments the other document does not mention` }),
      h('p', { class: 'panel__lede', text: run.mode === 'amendment' ? 'These stay as they were.' : 'No matching text was found. That does not mean they were missed.' }),
      h('ol', { class: 'findings__list' }, routine.map(finding))) : null);
}

// ---- export and reset ---------------------------------------------------------------------------
async function download(format) {
  setBusy(true);
  try {
    const text = await request('export', { format });
    const type = format === 'md' ? 'text/markdown' : 'application/json';
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = h('a', { href: url, download: `claimtrace-report.${format === 'md' ? 'md' : 'json'}` });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    $('add-status').textContent = `Report saved as ${format === 'md' ? 'Markdown' : 'JSON'}. It was made in this tab.`;
  } finally {
    setBusy(false);
  }
}

async function reset() {
  setBusy(true);
  try {
    register = await request('reset');
    samplesLoaded = false;
    docCache.clear();
    $('answer').replaceChildren();
    $('findings').replaceChildren();
    $('question').value = '';
    render();
    $('add-status').textContent = 'All documents removed from this tab.';
    $('load-samples').focus();
  } finally {
    setBusy(false);
  }
}

// ---- wiring -------------------------------------------------------------------------------------
function wire() {
  $('app').hidden = false;
  $('load-samples').addEventListener('click', loadSamples);
  $('file-input').addEventListener('change', (e) => {
    const files = [...e.target.files];
    e.target.value = '';
    if (files.length) addFiles(files, files.length === 1 ? files[0].name : `${files.length} files`);
  });
  const drop = $('drop');
  drop.addEventListener('dragover', (e) => {
    e.preventDefault();
    drop.classList.add('is-over');
  });
  drop.addEventListener('dragleave', () => drop.classList.remove('is-over'));
  drop.addEventListener('drop', (e) => {
    e.preventDefault();
    drop.classList.remove('is-over');
    if ($('file-input').disabled) return;
    const files = [...(e.dataTransfer?.files || [])];
    if (files.length) addFiles(files, files.length === 1 ? files[0].name : `${files.length} files`);
  });
  $('ask-form').addEventListener('submit', ask);
  $('check-form').addEventListener('submit', check);
  $('export-json').addEventListener('click', () => download('json'));
  $('export-md').addEventListener('click', () => download('md'));
  $('reset').addEventListener('click', reset);
  $('viewer-close').addEventListener('click', closeViewer);
  $('viewer').addEventListener('close', () => {
    if (viewerReturn && viewerReturn.isConnected) viewerReturn.focus();
    viewerReturn = null;
  });
  $('viewer').addEventListener('click', (e) => {
    if (e.target === $('viewer')) closeViewer(); // a click on the backdrop
  });
  startEngine();
}

wire();
