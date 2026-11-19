/* ClaimTrace Evidence page. Progressive: the headline answers, the chart and the tables are static HTML written by
   scripts/build_site_data.py. This file adds the test-set switch and the case browser (data from ../data/cases.json).
   Every piece of case data is inserted as text, never as markup. */
(function () {
  'use strict';

  var VERDICTS = {
    consistent: 'consistent', contradicted: 'contradicted', partially_supported: 'partially supported',
    not_addressed: 'not addressed', ambiguous: 'ambiguous', needs_human_review: 'needs human review',
    missing: 'no finding', in_force: 'in force', replaced: 'replaced', deleted: 'deleted', stated: 'stated',
    implied: 'implied'
  };
  var PAGE_SIZE = 20;

  function say(v) { return v == null ? 'none' : (VERDICTS[v] || String(v).replace(/_/g, ' ')); }

  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v == null || v === false) return;
        if (k === 'text') el.textContent = v;
        else if (k === 'class') el.className = v;
        else el.setAttribute(k, v === true ? '' : v);
      });
    }
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c == null || c === false) continue;
      if (Array.isArray(c)) c.forEach(function (x) { if (x != null && x !== false) el.append(x); });
      else el.append(c);
    }
    return el;
  }

  /* ---------------------------------------------------------------- test-set switch */
  var sw = document.querySelector('[data-switch]');
  var chart = document.querySelector('[data-chart]');
  var tables = document.querySelector('[data-tables]');
  if (sw && chart && tables) {
    var showSet = function (set) {
      chart.querySelectorAll('.ev-set').forEach(function (s) { s.classList.toggle('is-current', s.dataset.set === set); });
      tables.querySelectorAll('.ev-table[data-set]').forEach(function (t) { t.classList.toggle('is-current', t.dataset.set === set); });
    };
    sw.hidden = false;
    chart.setAttribute('data-ready', '');
    tables.setAttribute('data-ready', '');
    tables.open = false;
    sw.addEventListener('change', function (e) { if (e.target.name === 'ev-set') showSet(e.target.value); });
    var checked = sw.querySelector('input:checked');
    showSet(checked ? checked.value : 'holdout');
  }

  /* ---------------------------------------------------------------- case browser */
  var root = document.querySelector('[data-cb]');
  if (!root || !window.fetch) return;
  var form = root.querySelector('[data-filters]');
  var list = root.querySelector('[data-list]');
  var countEl = root.querySelector('[data-count]');
  var detail = root.querySelector('[data-detail]');
  var pager = root.querySelector('[data-pager]');
  var pageEl = pager.querySelector('[data-page]');
  var prev = pager.querySelector('[data-prev]');
  var next = pager.querySelector('[data-next]');
  root.hidden = false;

  var data = null;
  var byId = {};
  var haystack = {};
  var page = 0;
  var current = null;

  function filters() {
    var f = {};
    ['set', 'suite', 'system', 'version', 'result', 'q'].forEach(function (k) { f[k] = form.elements[k].value; });
    return f;
  }

  function runFor(c, f) {
    for (var i = 0; i < data.runs.length; i++) {
      var r = data.runs[i];
      if (r.set === c.set && r.system === f.system && r.version === f.version) return r;
    }
    return null;
  }

  function resultFor(c, run) { return run ? (data.results[run.id] || {})[c.id] || null : null; }

  function matches(c, f) {
    if (f.set && c.set !== f.set) return false;
    if (f.suite && c.suite !== f.suite) return false;
    if (f.result) {
      var res = resultFor(c, runFor(c, f));
      if (!res) return false;
      if ((f.result === 'pass') !== res.pass) return false;
    }
    if (f.q) {
      var words = f.q.toLowerCase().split(/\s+/).filter(Boolean);
      var hay = haystack[c.id];
      for (var i = 0; i < words.length; i++) if (hay.indexOf(words[i]) === -1) return false;
    }
    return true;
  }

  function verdictEl(res) {
    if (!res) return h('span', { class: 'verdict verdict--none', text: 'Not run' });
    return h('span', { class: 'verdict ' + (res.pass ? 'verdict--pass' : 'verdict--fail'), text: res.pass ? 'Passed' : 'Failed' });
  }

  function renderList() {
    var f = filters();
    var shown = data.cases.filter(function (c) { return matches(c, f); });
    var pages = Math.max(1, Math.ceil(shown.length / PAGE_SIZE));
    if (page >= pages) page = pages - 1;
    var slice = shown.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
    var failed = shown.filter(function (c) { var r = resultFor(c, runFor(c, f)); return r && !r.pass; }).length;
    countEl.textContent = shown.length + (shown.length === 1 ? ' case' : ' cases') +
      (f.result ? '' : ', ' + failed + ' failed') + ' for ' + (f.system === 'rules' ? 'Rules ' : 'Keyword floor ') +
      f.version.replace('-postfix', ' post-fix').replace('-blind', ' blind') + '.';
    list.replaceChildren.apply(list, slice.map(function (c) {
      var res = resultFor(c, runFor(c, f));
      return h('li', { class: 'cb__item' },
        h('a', { href: '#case=' + encodeURIComponent(c.id), 'aria-current': current === c.id ? 'true' : null },
          h('span', null, h('span', { class: 'cb__id', text: c.id }), ' ',
            h('span', { class: 'cb__tag', text: data.suites[c.suite] + ', ' + (c.set === 'core' ? 'core' : 'amendments') })),
          verdictEl(res),
          h('span', { class: 'cb__desc', text: c.desc })));
    }));
    pager.hidden = pages < 2;
    pageEl.textContent = 'Page ' + (page + 1) + ' of ' + pages;
    prev.disabled = page === 0;
    next.disabled = page >= pages - 1;
  }

  /* Mark every occurrence of the given phrases inside a document's text (case-insensitive, whitespace-tolerant). */
  function marked(text, phrases) {
    var ranges = [];
    var lower = text.toLowerCase();
    phrases.forEach(function (p) {
      if (!p) return;
      var esc = p.toLowerCase().trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+');
      var re = new RegExp(esc, 'g');
      var m;
      while ((m = re.exec(lower)) !== null) { ranges.push([m.index, m.index + m[0].length]); if (!m[0].length) break; }
    });
    ranges.sort(function (a, b) { return a[0] - b[0]; });
    var out = [];
    var at = 0;
    ranges.forEach(function (r) {
      if (r[0] < at) return;
      out.push(text.slice(at, r[0]), h('mark', { text: text.slice(r[0], r[1]) }));
      at = r[1];
    });
    out.push(text.slice(at));
    return out;
  }

  function phrasesOf(c) {
    var g = c.gold || {};
    if (g.checks) return g.checks.map(function (x) { return x.q; });
    if (g.commitments) return g.commitments.map(function (x) { return x.q; });
    if (g.citations) return g.citations;
    if (g.quote_contains) return [g.quote_contains];
    return [];
  }

  function kv(pairs) {
    return h('dl', { class: 'cb__kv' }, pairs.map(function (p) {
      return [h('dt', { text: p[0] }), h('dd', { text: p[1] == null || p[1] === '' ? 'none' : String(p[1]) })];
    }));
  }

  function table(head, rows, caption) {
    return h('div', { class: 'ev-table', role: 'region', tabindex: '0', 'aria-label': caption },
      h('table', { class: 'cb__checks' },
        h('thead', null, h('tr', null, head.map(function (x) { return h('th', { scope: 'col', text: x }); }))),
        h('tbody', null, rows.map(function (r) {
          return h('tr', null, r.map(function (x) { return typeof x === 'object' && x ? h('td', null, x) : h('td', { text: x == null ? 'none' : String(x) }); }));
        }))));
  }

  function body(c, run, res) {
    var g = c.gold || {};
    var out = res ? res.out : null;
    var parts = [];
    if (c.suite === 'qa') {
      parts.push(h('h4', { text: 'The question' }), h('p', { class: 'cb__quote', text: c.question }));
      parts.push(h('h4', { text: 'The right answer' }), kv([['Status', say(g.status)]]));
      if (g.citations.length) parts.push(h('ul', { class: 'cb__list-plain' }, g.citations.map(function (q) { return h('li', { text: 'Must cite: “' + q + '”' }); })));
      parts.push(h('h4', { text: 'What ClaimTrace said' }));
      if (out) {
        parts.push(kv([['Status', say(out.status)], ['Confidence', out.conf], ['Gold quotes cited', out.cit_recall == null ? null : Math.round(out.cit_recall * 100) + '%']]));
        if (out.answer) parts.push(h('p', { class: 'cb__quote', text: out.answer }));
        if (out.citations && out.citations.length) parts.push(h('ul', { class: 'cb__list-plain' }, out.citations.map(function (q) { return h('li', { text: 'Cited: “' + q + '”' }); })));
      }
    } else if (g.checks) {
      parts.push(h('h4', { text: 'What is checked' }),
        h('p', { class: 'cb__meta', text: 'Each clause of “' + docTitle(c, c.base) + '” is checked against “' + docTitle(c, c.other) + '”.' }));
      parts.push(table(['#', 'Clause containing', 'Right answer', 'ClaimTrace said', 'Its reason', 'Result'],
        g.checks.map(function (ch, i) {
          var o = out && out.checks ? out.checks[i] : null;
          var ok = o && o.verdict === ch.verdict;
          return [String(i + 1), '“' + ch.q + '”', say(ch.verdict), o ? say(o.verdict) : null,
            o && o.why ? o.why : (out && out.note ? out.note : null),
            o ? h('span', { class: 'verdict ' + (ok ? 'verdict--pass' : 'verdict--fail'), text: ok ? 'Right' : 'Wrong' }) : null];
        }), 'Checks and verdicts'));
      if (g.effects.length) {
        parts.push(h('h4', { text: 'What the amendment does to each section' }));
        parts.push(table(['Section', 'Right answer', 'ClaimTrace said', 'Result'], g.effects.map(function (e, i) {
          var p = out && out.effects ? out.effects[i] : null;
          var ok = p === e.effect;
          return [e.section, say(e.effect), p ? say(p) : (out && out.note ? 'not computed' : null),
            p ? h('span', { class: 'verdict ' + (ok ? 'verdict--pass' : 'verdict--fail'), text: ok ? 'Right' : 'Wrong' }) : null];
        }), 'Section effects'));
      }
    } else if (c.suite === 'extraction') {
      parts.push(h('h4', { text: 'The right answer: labelled commitments' }));
      parts.push(table(['Quote containing', 'Type', 'Who owes it', 'Strength'], g.commitments.map(function (x) {
        return ['“' + x.q + '”', say(x.type), x.party || 'none stated', say(x.modality)];
      }), 'Labelled commitments'));
      if (g.max_extra) parts.push(h('p', { class: 'cb__meta', text: g.max_extra + ' extra commitment(s) tolerated.' }));
      if (out) {
        parts.push(h('h4', { text: 'What ClaimTrace extracted (' + out.found + ' matched, ' + out.missed + ' missed, ' + out.extra + ' extra)' }));
        parts.push(table(['Quote', 'Type', 'Who owes it', 'Strength', 'Confidence'], out.items.map(function (x) {
          return [x.q, say(x.type), x.party || 'none', say(x.modality), x.conf + (x.review ? ', flagged for review' : '')];
        }), 'Extracted commitments'));
      }
    } else if (c.suite === 'deadline') {
      parts.push(h('h4', { text: 'The clause' }), h('p', { class: 'cb__quote', text: '“' + g.quote_contains + '”' }));
      parts.push(h('h4', { text: 'The right answer' }), kv([['Kind', say(g.deadline_kind)], ['Date', g.date], ['Offset (days)', g.offset_days],
        ['Business days', g.business_days == null ? null : (g.business_days ? 'yes' : 'no')], ['Anchor', g.anchor_contains],
        ['Has a condition', g.has_condition ? 'yes' : 'no'], ['Has an exception', g.has_exception ? 'yes' : 'no']]));
      parts.push(h('h4', { text: 'What ClaimTrace said' }));
      parts.push(out ? kv([['Kind', say(out.kind)], ['Wording', out.raw], ['Date', out.date], ['Offset (days)', out.offset_days],
        ['Business days', out.business_days == null ? null : (out.business_days ? 'yes' : 'no')], ['Anchor', out.anchor]])
        : h('p', { text: 'It did not extract this commitment.' }));
    } else if (c.suite === 'ambiguous') {
      parts.push(h('h4', { text: 'The clause' }), h('p', { class: 'cb__quote', text: '“' + g.quote_contains + '”' }));
      parts.push(h('h4', { text: 'The right answer' }), kv([['Flag for review', 'yes'], ['Confidence at most', g.max_confidence]]));
      parts.push(h('h4', { text: 'What ClaimTrace said' }));
      parts.push(out ? kv([['Flagged for review', out.needs_review ? 'yes' : 'no'], ['Confidence', out.confidence]])
        : h('p', { text: 'It did not extract this commitment.' }));
    }
    return parts;
  }

  function docTitle(c, key) {
    for (var i = 0; i < c.docs.length; i++) if (c.docs[i].key === key) return c.docs[i].title || key;
    return key;
  }

  function renderDetail(id, focus) {
    var c = byId[id];
    current = c ? id : null;
    if (!c) {
      detail.replaceChildren(h('p', { class: 'cb__empty', text: 'No published case has the id “' + id + '”. Holdout cases are sealed and not shown.' }));
      return;
    }
    var f = filters();
    var run = runFor(c, f);
    var res = resultFor(c, run);
    var verdict;
    if (!res) {
      verdict = h('div', { class: 'cb__verdict' }, h('p', { text: 'No run of ' + (f.system === 'rules' ? 'Rules' : 'the keyword floor') + ' ' + f.version + ' on this set. Pick another version above.' }));
    } else {
      verdict = h('div', { class: 'cb__verdict' + (res.pass ? ' is-pass' : '') },
        h('p', null, h('strong', { text: (res.pass ? 'Passed' : 'Failed') + ' with ' + run.label + '. ' }),
          res.pass ? 'Every check in this case was right.' : 'Why it failed:'),
        res.why.length ? h('ul', null, res.why.map(function (w) { return h('li', { text: w }); })) : null);
    }
    var phrases = phrasesOf(c);
    var docs = c.docs.map(function (d, i) {
      return h('details', { class: 'cb__doc', open: i < 2 ? true : null },
        h('summary', { text: (d.title || d.key) + ' (' + say(d.type) + (d.amends ? ', amends ' + docTitle(c, d.amends) : '') + ')' }),
        h('pre', { tabindex: '0' }, marked(d.text, phrases)));
    });
    var others = data.runs.filter(function (r) { return r.set === c.set; }).map(function (r) {
      var x = (data.results[r.id] || {})[c.id];
      return h('li', null, r.label + ': ', verdictEl(x));
    });
    var titleId = 'case-title';
    detail.setAttribute('aria-labelledby', titleId);
    detail.replaceChildren.apply(detail, [].concat(
      h('a', { class: 'cb__back', href: '#cases', text: 'Back to the list' }),
      h('h3', { id: titleId, text: c.id }),
      h('p', { class: 'cb__meta', text: data.suites[c.suite] + ' suite, ' + (c.set === 'core' ? 'core set' : 'amendments set') }),
      h('p', { text: c.desc }),
      verdict,
      body(c, run, res),
      h('h4', { text: 'The documents' }),
      h('p', { class: 'cb__meta', text: 'Highlighted: the wording the right answer refers to.' }),
      docs,
      h('h4', { text: 'This case in every run' }),
      h('ul', { class: 'cb__list-plain' }, others)));
    renderList();
    if (focus) {
      detail.focus({ preventScroll: true });
      detail.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    }
  }

  function readHash(focus) {
    var raw = location.hash.replace(/^#/, '');
    var m = /^case=(.+)$/.exec(raw);
    if (m) renderDetail(decodeURIComponent(m[1]), focus);
  }

  function preset(spec) {
    var p = spec.split(':');
    form.elements.set.value = p[0] || '';
    form.elements.suite.value = p[1] || '';
    form.elements.result.value = p[2] || '';
    form.elements.system.value = 'rules';
    form.elements.version.value = 'v0.2';
    form.elements.q.value = '';
    page = 0;
    renderList();
  }

  form.addEventListener('input', function () { page = 0; renderList(); if (current) renderDetail(current, false); });
  form.addEventListener('submit', function (e) { e.preventDefault(); });
  prev.addEventListener('click', function () { if (page > 0) { page--; renderList(); list.querySelector('a') && list.querySelector('a').focus(); } });
  next.addEventListener('click', function () { page++; renderList(); list.querySelector('a') && list.querySelector('a').focus(); });
  window.addEventListener('hashchange', function () { if (data) readHash(true); });
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('[data-preset]');
    if (a && data) preset(a.getAttribute('data-preset'));
  });

  fetch('../data/cases.json').then(function (r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(function (d) {
    data = d;
    var suiteSel = form.elements.suite;
    Object.keys(d.suites).forEach(function (k) { suiteSel.append(h('option', { value: k, text: d.suites[k] })); });
    d.cases.forEach(function (c) {
      byId[c.id] = c;
      haystack[c.id] = [c.id, c.desc, c.question || '', JSON.stringify(c.gold), c.docs.map(function (x) { return x.title + ' ' + x.text; }).join(' ')].join(' ').toLowerCase();
    });
    renderList();
    readHash(true);
  }).catch(function (err) {
    countEl.textContent = 'Cases did not load (' + err.message + ').';
  });
})();
