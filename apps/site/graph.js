/* ClaimTraceGraph: the evidence map as a component. One lane per document, its clauses as buttons ("clips"),
   connectors between them routed through the gutters, a side panel with the clause in focus (its verbatim
   words and what links to it), a short spoken status, and every link as a plain list.

     ClaimTraceGraph.mount(el, data, options) -> { update(options), select(id), destroy() }

   `data` is the model claimtrace.browser.graph() builds (lanes, links, kinds, shown). When `el` already holds
   the map's markup (the home page renders it at build time, so it shows without scripting) the component
   takes it over; otherwise it renders the legend, lanes, panel and list into `el`.

   Options: lanes (lane keys to show), selected (clip id), highlight (clip ids; the rest are dimmed, or null),
   onSelect(clip, lane), onLink(link) (adds "Show the finding" to links that carry one, and makes connectors
   clickable), id (prefix for element ids), label (accessible name of the map).

   Keyboard: one tab stop; arrow keys move along a lane and between lanes, Home and End jump within a lane.
   Document text is untrusted: it is only ever set with textContent. */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';

  // link kind -> [status word, icon]. A status is always a word and an icon, never colour alone.
  var STATUS = {
    replaces: ['Replaced', 'i-replaced'], changes: ['Changed', 'i-replaced'], contradicts: ['Contradicted', 'i-contradicts'],
    partly: ['Partly supported', 'i-partly'], supports: ['Supported', 'i-supports'], review: ['Needs review', 'i-review'],
    states: ['States it', 'i-supports'], replaced: ['Replaced', 'i-replaced'], conflicts: ['Disagrees', 'i-contradicts'],
    context: ['Context', 'i-evidence'], notfound: ['Not found', 'i-none'], notmentioned: ['Not mentioned', 'i-none']
  };
  // clip state -> [word, icon]
  var STATE = {
    replaced: ['Replaced', 'i-replaced'], in_force: ['In force', 'i-inforce'], evidence: ['Evidence', 'i-evidence'],
    review: ['Needs review', 'i-review'], answer: ['Answer', 'i-supports'], absent: ['Not mentioned', 'i-none']
  };
  var ANSWER = {
    stated: ['Found in the documents', 'i-supports'], implied: ['Implied, not stated outright', 'i-partly'],
    contradicted: ['The documents disagree', 'i-contradicts'], not_addressed: ['Not found in the documents', 'i-none'],
    ambiguous: ['Unclear: more than one reading', 'i-review'], needs_human_review: ['A person needs to check this', 'i-review']
  };
  var GRAVITY = ['replaces', 'contradicts', 'conflicts', 'changes', 'replaced', 'partly', 'review', 'notfound',
    'notmentioned', 'supports', 'states', 'context'];

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function icon(id) {
    var s = document.createElementNS(NS, 'svg');
    s.setAttribute('class', 'icon');
    s.setAttribute('aria-hidden', 'true');
    var u = document.createElementNS(NS, 'use');
    u.setAttribute('href', '#' + id);
    s.appendChild(u);
    return s;
  }
  function stateOf(c) { return c.state || c.effect || 'evidence'; }
  function stateWord(c) {
    if (c.node === 'answer') return ANSWER[c.status] || ANSWER.not_addressed;
    return STATE[stateOf(c)] || STATE.evidence;
  }
  function statusOf(kind) { return STATUS[kind] || STATUS.review; }
  // "§2.1", or "¶3" for a passage without a section number
  function secLabel(c) { return !c.section ? '' : c.section.charAt(0) === '¶' ? c.section : '§' + c.section; }
  function secWords(c) { return !c.section ? '' : c.section.charAt(0) === '¶' ? 'paragraph ' + c.section.slice(1) : 'section ' + c.section; }

  /* ---- markup, for a map that was not rendered at build time (the same structure scripts/build_site_data.py
     writes for the home page) ---- */
  function renderInto(host, data, o) {
    var linked = {};
    data.links.forEach(function (l) { linked[l.from] = linked[l.to] = true; });
    host.textContent = '';
    host.classList.add('graph');
    var shown = data.shown || {};
    var capped = [];
    if (shown.documents && shown.documents[0] < shown.documents[1]) capped.push(shown.documents[0] + ' of ' + shown.documents[1] + ' documents');
    if (shown.clips && shown.clips[0] < shown.clips[1]) capped.push(shown.clips[0] + ' of ' + shown.clips[1] + ' clauses');
    if (capped.length) host.appendChild(el('p', 'graph__note', 'Showing ' + capped.join(' and ') + ', the ones with links first, to keep the map readable. The lists below have everything.'));

    var kinds = GRAVITY.filter(function (k) { return data.links.some(function (l) { return l.kind === k; }); });
    var states = ['in_force', 'replaced', 'review'].filter(function (s) {
      return data.lanes.some(function (lane) { return lane.clips.some(function (c) { return stateOf(c) === s; }); });
    });
    if (kinds.length || states.length) {
      var keys = el('div', 'graph__keys');
      if (states.length) {
        var sl = el('ul', 'legend legend--states');
        sl.setAttribute('aria-label', 'Clause states');
        states.forEach(function (s) {
          var li = el('li', 'legend__item legend__item--' + s.replace('_', '-'));
          li.appendChild(el('span', 'legend__clip'));
          li.appendChild(icon(STATE[s][1]));
          li.appendChild(document.createTextNode(STATE[s][0]));
          sl.appendChild(li);
        });
        keys.appendChild(sl);
      }
      if (kinds.length) {
        var kl = el('ul', 'legend');
        kl.setAttribute('aria-label', 'Kinds of link');
        kinds.forEach(function (k) {
          var li = el('li', 'legend__item legend__item--' + k);
          var w = document.createElementNS(NS, 'svg');
          w.setAttribute('class', 'legend__wire');
          w.setAttribute('viewBox', '0 0 32 8');
          w.setAttribute('aria-hidden', 'true');
          var p = document.createElementNS(NS, 'path');
          p.setAttribute('d', 'M0 4h32');
          w.appendChild(p);
          li.appendChild(w);
          li.appendChild(icon(statusOf(k)[1]));
          li.appendChild(document.createTextNode(statusOf(k)[0]));
          kl.appendChild(li);
        });
        keys.appendChild(kl);
      }
      host.appendChild(keys);
    }

    var map = el('div', 'map map--fluid');
    map.setAttribute('data-map', '');
    map.setAttribute('role', 'group');
    map.setAttribute('aria-label', o.label || 'Evidence map');
    var keysHelp = el('p', 'visually-hidden', 'Each clause is a button. Arrow keys move along a document and between documents; the panel shows the clause in focus and what links to it.');
    keysHelp.id = o.id + '-keys';
    map.setAttribute('aria-describedby', keysHelp.id);
    map.appendChild(keysHelp);
    var lanesEl = el('div', 'map__lanes');
    lanesEl.setAttribute('data-map-lanes', '');
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'map__wires');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    lanesEl.appendChild(svg);
    data.lanes.forEach(function (lane, li) {
      var div = el('div', 'lane lane--' + (lane.type || 'document'));
      div.setAttribute('data-lane', lane.key);
      var name = el('p', 'lane__name', lane.name);
      name.id = o.id + '-lane-' + li;
      div.appendChild(name);
      var ul = el('ul', 'lane__track');
      ul.setAttribute('aria-labelledby', name.id);
      lane.clips.forEach(function (c) {
        var st = stateOf(c).replace('_', '-');
        var w = c.node ? 3 : Math.max(1, Math.min(6, Math.round((c.text || '').length / 40)));
        var slot = el('li', 'clip-slot clip-slot--w' + w + ' clip-slot--' + st);
        var b = el('button', 'clip clip--' + st + (linked[c.id] ? ' is-linked' : ''));
        b.type = 'button';
        b.setAttribute('data-clip', c.id);
        b.setAttribute('aria-pressed', 'false');
        b.setAttribute('aria-controls', o.id + '-panel');
        if (c.node === 'answer') {
          b.setAttribute('aria-label', 'Answer: ' + stateWord(c)[0].toLowerCase());
          b.appendChild(icon(stateWord(c)[1]));
          b.appendChild(el('span', 'clip__word', 'Answer'));
        } else if (c.node === 'absent') {
          b.setAttribute('aria-label', 'Not mentioned in ' + lane.name);
          b.appendChild(icon('i-none'));
          b.appendChild(el('span', 'clip__word', 'Not mentioned'));
        } else {
          var said = { replaced: ', replaced', 'in-force': ', in force', review: ', needs review' }[st] || '';
          b.setAttribute('aria-label', lane.name + ' ' + secWords(c) + said);
          if (st === 'replaced') b.appendChild(icon('i-replaced'));
          if (st === 'review') b.appendChild(icon('i-review'));
          b.appendChild(el('span', 'num', c.section));
        }
        slot.appendChild(b);
        ul.appendChild(slot);
      });
      div.appendChild(ul);
      lanesEl.appendChild(div);
    });
    map.appendChild(lanesEl);
    var panel = el('div', 'map__panel');
    panel.id = o.id + '-panel';
    map.appendChild(panel);
    var status = el('p', 'visually-hidden');
    status.id = o.id + '-status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-atomic', 'true');
    map.appendChild(status);
    host.appendChild(map);

    if (data.links.length) {
      var details = el('details', 'wire-list');
      details.appendChild(el('summary', '', 'Every link, as a list (' + data.links.length + ')'));
      var list = el('ul');
      var where = index(data);
      data.links.forEach(function (l) {
        var li = el('li', 'wire-list__item wire-list__item--' + l.kind);
        li.appendChild(statusEl(l.kind));
        li.appendChild(document.createTextNode(' '));
        var t = el('span');
        t.appendChild(el('span', 'wire-list__pair', citeOf(where, l.to) + ', ' + data.kinds[l.kind].in.toLowerCase() + ' ' + citeOf(where, l.from) + '.'));
        if (l.note) {
          t.appendChild(document.createTextNode(' '));
          t.appendChild(el('span', 'wire-list__note', l.note));
        }
        li.appendChild(t);
        list.appendChild(li);
      });
      details.appendChild(list);
      host.appendChild(details);
    }
    return map;
  }

  function statusEl(kind) {
    var s = el('span', 'status status--' + kind);
    s.appendChild(icon(statusOf(kind)[1]));
    s.appendChild(document.createTextNode(statusOf(kind)[0]));
    return s;
  }
  function index(data) {
    var clips = {}, laneOf = {};
    data.lanes.forEach(function (lane) { lane.clips.forEach(function (c) { clips[c.id] = c; laneOf[c.id] = lane; }); });
    return { clips: clips, laneOf: laneOf };
  }
  function citeOf(ix, id) {
    var c = ix.clips[id], lane = ix.laneOf[id];
    if (c.node === 'answer') return 'The answer';
    if (c.node === 'absent') return lane.name + ' (not mentioned)';
    return lane.name + (c.section ? ' ' + secLabel(c) : '');
  }

  function filter(data, keys) {
    if (!keys) return data;
    var lanes = data.lanes.filter(function (l) { return keys.indexOf(l.key) >= 0; });
    var ids = {};
    lanes.forEach(function (l) { l.clips.forEach(function (c) { ids[c.id] = true; }); });
    var out = {};
    Object.keys(data).forEach(function (k) { out[k] = data[k]; });
    out.lanes = lanes;
    out.links = data.links.filter(function (l) { return ids[l.from] && ids[l.to]; });
    return out;
  }

  /* ---- the component ---- */
  function mount(host, data, options) {
    var o = {};
    Object.keys(options || {}).forEach(function (k) { o[k] = options[k]; });
    o.id = o.id || 'graph';
    data = filter(data, o.lanes);
    var hydrate = !!host.querySelector('[data-map-lanes]');
    var map = hydrate ? host : renderInto(host, data, o);
    var lanesEl = map.querySelector('[data-map-lanes]');
    var svg = map.querySelector('.map__wires');
    var panel = map.querySelector('.map__panel');
    var statusEl_ = map.querySelector('[role="status"]');
    var reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
    var ix = index(data);
    var clips = ix.clips, laneOf = ix.laneOf;
    var buttons = Array.prototype.slice.call(map.querySelectorAll('[data-clip]'));
    var byId = {};
    buttons.forEach(function (b) { byId[b.dataset.clip] = b; });
    var laneEls = Array.prototype.slice.call(map.querySelectorAll('.lane'));
    var rows = laneEls.map(function (lane) {
      return Array.prototype.slice.call(lane.querySelectorAll('[data-clip]'));
    });
    if (!buttons.length) return { update: function () {}, select: function () {}, destroy: function () {} };
    var first = data.links.length ? data.links[0].to : buttons[0].dataset.clip;
    var pinned = o.selected && clips[o.selected] ? o.selected : first;
    var wires = [];
    var dim = null;
    if (o.onLink) map.classList.add('map--links');

    function cite(id) { return citeOf(ix, id); }
    function linksOf(id) { return data.links.filter(function (l) { return l.to === id || l.from === id; }); }

    /* ---- panel ---- */
    function renderPanel(id) {
      var c = clips[id], lane = laneOf[id], st = stateWord(c);
      var frag = document.createDocumentFragment();
      var where = el('p', 'map__where');
      if (c.node === 'answer') {
        where.appendChild(el('span', 'map__doc', 'The answer'));
      } else if (c.node === 'absent') {
        where.appendChild(el('span', 'map__doc', lane.name));
      } else {
        where.appendChild(el('span', 'map__doc', lane.name));
        where.appendChild(document.createTextNode(' '));
        where.appendChild(el('span', 'num map__sec', secLabel(c)));
      }
      frag.appendChild(where);
      if (!c.node) frag.appendChild(el('p', 'map__heading', c.heading || ''));
      var state = el('p', 'map__state map__state--' + (c.node ? c.node : stateOf(c).replace('_', '-')));
      state.appendChild(icon(st[1]));
      state.appendChild(document.createTextNode(st[0]));
      frag.appendChild(state);
      var file;
      if (c.node === 'answer') {
        frag.appendChild(el('p', 'map__answer', c.text));
        file = el('p', 'map__file', 'The engine\'s answer, in its own words. The clauses it quotes are below.');
      } else if (c.node === 'absent') {
        file = el('p', 'map__file', 'Nothing in this document matches the clauses below. That does not mean they were missed.');
      } else if (c.withheld) {
        file = el('p', 'map__file', 'Wording not shown on this page. Read it on ');
        var go = el('a', '', 'Try it');
        go.href = 'try/';
        file.appendChild(go);
        file.appendChild(document.createTextNode(', where the full sample contract is loaded.'));
      } else {
        frag.appendChild(el('blockquote', 'map__quote', c.text));
        file = el('p', 'map__file', 'Verbatim from ');
        file.appendChild(el('span', 'num', lane.file || lane.title || lane.name));
      }
      frag.appendChild(file);
      frag.appendChild(el('h3', 'map__links-title', 'Links'));
      var ls = linksOf(id);
      if (!ls.length) {
        frag.appendChild(el('p', 'map__none', c.node === 'answer' ? 'The answer quotes no clause.' : 'Nothing in the other documents links to this clause.'));
      } else {
        var ul = el('ul', 'map__links');
        ls.forEach(function (l) {
          var incoming = l.to === id, other = incoming ? l.from : l.to;
          var li = el('li', 'map__link');
          li.appendChild(statusEl(l.kind));
          var t = el('span', 'map__link-text', data.kinds[l.kind][incoming ? 'in' : 'out'] + ' ');
          var b = el('button', 'map__cite', cite(other));
          b.type = 'button';
          b.dataset.go = other;
          t.appendChild(b);
          if (l.note) t.appendChild(el('span', 'map__note', l.note));
          if (o.onLink && l.finding != null) {
            var f = el('button', 'map__finding', 'Show the finding');
            f.type = 'button';
            f.dataset.finding = String(data.links.indexOf(l));
            t.appendChild(f);
          }
          li.appendChild(t);
          ul.appendChild(li);
        });
        frag.appendChild(ul);
      }
      panel.textContent = '';
      panel.appendChild(frag);
    }

    /* ---- wires ----
       Connectors run like tracks: they leave a clip vertically, turn into the gutter between two lanes, and
       cross any lane in between through a gap between its clips (or round its end), never across a clip.
       Each crossing gets its own gap and each run its own height in the gutter, so no piece of wire floats
       between clips it does not join. */
    var laneIndex = {};
    rows.forEach(function (row, i) { row.forEach(function (b) { laneIndex[b.dataset.clip] = i; }); });

    function rounded(pts, radius) {
      var clean = [pts[0]];
      for (var i = 1; i < pts.length; i++) {
        var q = clean[clean.length - 1];
        if (Math.abs(pts[i][0] - q[0]) > 0.5 || Math.abs(pts[i][1] - q[1]) > 0.5) clean.push(pts[i]);
      }
      var d = 'M' + clean[0][0] + ' ' + clean[0][1];
      for (var k = 1; k < clean.length - 1; k++) {
        var p0 = clean[k - 1], p1 = clean[k], p2 = clean[k + 1];
        var l1 = Math.hypot(p1[0] - p0[0], p1[1] - p0[1]), l2 = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);
        var r = Math.min(radius, l1 / 2, l2 / 2);
        var a = [p1[0] - (p1[0] - p0[0]) / l1 * r, p1[1] - (p1[1] - p0[1]) / l1 * r];
        var b = [p1[0] + (p2[0] - p1[0]) / l2 * r, p1[1] + (p2[1] - p1[1]) / l2 * r];
        d += ' L' + a[0] + ' ' + a[1] + ' Q' + p1[0] + ' ' + p1[1] + ' ' + b[0] + ' ' + b[1];
      }
      var last = clean[clean.length - 1];
      return d + ' L' + last[0] + ' ' + last[1];
    }

    function draw() {
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      wires = [];
      if (!map.isConnected || getComputedStyle(svg).display === 'none') { mark(current, false); return; }
      var box = lanesEl.getBoundingClientRect();
      var pad = parseFloat(getComputedStyle(lanesEl).paddingLeft) || 24;
      var lanes = laneEls.map(function (l) {
        var r = l.getBoundingClientRect(), name = l.querySelector('.lane__name');
        return { top: r.top - box.top, bottom: r.bottom - box.top, labelRight: name ? name.getBoundingClientRect().right - box.left : 0 };
      });
      // where a wire may pass through each lane: the gaps between its clips, and both ends of the lane
      var channels = rows.map(function (row) {
        var rs = row.map(function (b) { return b.getBoundingClientRect(); });
        var xs = [pad / 2, box.width - pad / 2];
        var oneLine = rs.every(function (r) { return Math.abs(r.top - rs[0].top) < 1; });
        if (oneLine) for (var i = 1; i < rs.length; i++) xs.push((rs[i - 1].right + rs[i].left) / 2 - box.left);
        return xs.map(function (x) { return { x: x, used: 0 }; });
      });
      // a clip's attachment point: its centre, moved clear of the lane name when the wire uses the top edge
      function attach(btn, lane, top) {
        var r = btn.getBoundingClientRect();
        var x = r.left + r.width / 2 - box.left, left = r.left - box.left, right = r.right - box.left;
        if (top && x < lanes[lane].labelRight + 10) x = Math.min(lanes[lane].labelRight + 10, right - 8, Math.max(x, left + 8));
        return [x, (top ? r.top : r.bottom) - box.top];
      }
      var runs = {}; // gutter index (between lane g-1 and lane g) -> the horizontal runs in it
      var routes = [];
      data.links.forEach(function (l) {
        var a = byId[l.from], b = byId[l.to];
        if (!a || !b) return;
        var ia = laneIndex[l.from], ib = laneIndex[l.to];
        if (ia === ib) return; // links always join two documents
        var up = ia > ib, step = up ? -1 : 1;
        var start = attach(a, ia, up), end = attach(b, ib, !up);
        var pts = [start], x = start[0], segs = [];
        for (var lane = ia; lane !== ib; lane += step) {
          var gutter = up ? lane : lane + 1;
          var nextLane = lane + step, nx = end[0];
          if (nextLane !== ib) {
            var best = null, cost = Infinity;
            channels[nextLane].forEach(function (c) {
              var v = Math.abs(c.x - x) + Math.abs(c.x - end[0]) + c.used * 1e4;
              if (v < cost) { cost = v; best = c; }
            });
            best.used++;
            nx = best.x;
          }
          var seg = { gutter: gutter, from: pts.length, y: 0 };
          pts.push([x, 0], [nx, 0]);
          segs.push(seg);
          (runs[gutter] = runs[gutter] || []).push(seg);
          x = nx;
        }
        pts.push(end);
        routes.push({ link: l, pts: pts, segs: segs });
      });
      // spread the runs in each gutter over its height, a few pixels apart
      Object.keys(runs).forEach(function (g) {
        var list = runs[g], top = lanes[g - 1].bottom, bottom = lanes[g].top, mid = (top + bottom) / 2;
        var room = Math.max(0, bottom - top - 16), gap = list.length > 1 ? Math.min(4, room / (list.length - 1)) : 0;
        list.forEach(function (s, i) { s.y = mid + (i - (list.length - 1) / 2) * gap; });
      });
      routes.forEach(function (r) {
        r.segs.forEach(function (s) { r.pts[s.from][1] = s.y; r.pts[s.from + 1][1] = s.y; });
        var d = rounded(r.pts, 10);
        var p = document.createElementNS(NS, 'path');
        p.setAttribute('d', d);
        p.setAttribute('class', 'wire wire--' + r.link.kind);
        svg.appendChild(p);
        if (o.onLink && r.link.finding != null) {
          var hit = document.createElementNS(NS, 'path');
          hit.setAttribute('d', d);
          hit.setAttribute('class', 'wire-hit');
          hit.dataset.finding = String(data.links.indexOf(r.link));
          svg.appendChild(hit);
        }
        wires.push({ link: r.link, path: p });
      });
      mark(current, false);
    }

    /* ---- selection ---- */
    var current = pinned;
    function mark(id, animate) {
      current = id;
      map.classList.add('has-active');
      var related = {};
      linksOf(id).forEach(function (l) { related[l.to === id ? l.from : l.to] = l.kind; });
      buttons.forEach(function (b) {
        var cid = b.dataset.clip;
        b.setAttribute('aria-pressed', cid === pinned ? 'true' : 'false');
        b.classList.toggle('is-related', !!related[cid]);
        if (related[cid]) b.dataset.rel = related[cid]; else delete b.dataset.rel;
        if (dim) b.classList.toggle('is-dim', !dim[cid]);
      });
      wires.forEach(function (w) {
        var on = w.link.to === id || w.link.from === id;
        w.path.classList.toggle('is-active', on);
        if (dim) w.path.classList.toggle('is-dim', !dim[w.link.to] && !dim[w.link.from]);
        w.path.classList.remove('is-drawing');
        if (on && animate && !reduce.matches) {
          var len = Math.ceil(w.path.getTotalLength());
          w.path.style.strokeDasharray = w.path.classList.contains('wire--replaces') || w.path.classList.contains('wire--contradicts') || w.path.classList.contains('wire--supports') ? len + ' ' + len : '';
          w.path.style.setProperty('--len', len);
          void w.path.getBoundingClientRect();
          if (w.path.style.strokeDasharray) w.path.classList.add('is-drawing');
        } else {
          w.path.style.strokeDasharray = '';
        }
      });
    }
    function show(id, animate) {
      if (!clips[id]) return;
      if (id !== current) renderPanel(id);
      mark(id, animate);
    }
    /* A short spoken status when a clause is chosen (click, Enter, arrow keys), never on hover: the panel
       itself is not a live region, so moving along a lane does not re-read whole clauses. */
    var said = '';
    function announce(id) {
      if (!statusEl_ || !clips[id]) return;
      var ins = data.links.filter(function (l) { return l.to === id; });
      ins.sort(function (a, b) { return GRAVITY.indexOf(a.kind) - GRAVITY.indexOf(b.kind); });
      var word = ins.length ? statusOf(ins[0].kind)[0] : stateWord(clips[id])[0];
      var msg = cite(id) + ', ' + word.toLowerCase();
      if (msg === said) return;
      said = msg;
      statusEl_.textContent = msg;
    }
    function pin(id, animate) {
      announce(id);
      pinned = id;
      buttons.forEach(function (b) { b.tabIndex = b.dataset.clip === id ? 0 : -1; });
      show(id, animate);
      if (o.onSelect) o.onSelect(clips[id], laneOf[id]);
    }

    /* roving tab stop */
    buttons.forEach(function (b) { b.tabIndex = b.dataset.clip === pinned ? 0 : -1; });

    function stacked() {
      return panel.getBoundingClientRect().top >= lanesEl.getBoundingClientRect().bottom - 1;
    }
    function onClick(e) {
      var fin = e.target.closest('[data-finding]');
      if (fin && o.onLink) {
        o.onLink(data.links[Number(fin.dataset.finding)]);
        return;
      }
      var go = e.target.closest('[data-go]');
      if (go) {
        var target = byId[go.dataset.go];
        pin(go.dataset.go, true);
        if (target) target.focus({ preventScroll: false });
        return;
      }
      var b = e.target.closest('[data-clip]');
      if (!b) return;
      pin(b.dataset.clip, true);
      if (stacked()) {
        var r = panel.getBoundingClientRect();
        if (r.top > window.innerHeight || r.bottom < 0) panel.scrollIntoView({ block: 'nearest', behavior: reduce.matches ? 'auto' : 'smooth' });
      }
    }
    function onFocus(e) {
      var b = e.target.closest('[data-clip]');
      if (b && b.dataset.clip !== pinned) pin(b.dataset.clip, true);
    }
    function onOver(e) {
      if (e.pointerType !== 'mouse') return;
      var b = e.target.closest('[data-clip]');
      if (b) show(b.dataset.clip, true);
    }
    function onLeave() { show(pinned, false); }
    function onKey(e) {
      var b = e.target.closest('[data-clip]');
      if (!b) return;
      var r = -1, i = -1;
      rows.forEach(function (row, ri) { var k = row.indexOf(b); if (k >= 0) { r = ri; i = k; } });
      var next = null;
      if (e.key === 'ArrowRight') next = rows[r][Math.min(i + 1, rows[r].length - 1)];
      else if (e.key === 'ArrowLeft') next = rows[r][Math.max(i - 1, 0)];
      else if (e.key === 'Home') next = rows[r][0];
      else if (e.key === 'End') next = rows[r][rows[r].length - 1];
      else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        var to = rows[r + (e.key === 'ArrowDown' ? 1 : -1)];
        if (to && to.length) {
          var cx = b.getBoundingClientRect().left + b.offsetWidth / 2, best = null, bd = Infinity;
          to.forEach(function (c) { var d = Math.abs(c.getBoundingClientRect().left + c.offsetWidth / 2 - cx); if (d < bd) { bd = d; best = c; } });
          next = best;
        } else next = b;
      } else return;
      e.preventDefault();
      if (next) next.focus();
    }
    map.addEventListener('click', onClick);
    lanesEl.addEventListener('focusin', onFocus);
    lanesEl.addEventListener('pointerover', onOver);
    lanesEl.addEventListener('pointerleave', onLeave);
    lanesEl.addEventListener('keydown', onKey);

    function setHighlight(ids) {
      if (!ids) {
        dim = null;
        buttons.forEach(function (b) { b.classList.remove('is-dim'); });
        wires.forEach(function (w) { w.path.classList.remove('is-dim'); });
        map.classList.remove('has-dim');
      } else {
        dim = {};
        ids.forEach(function (id) { dim[id] = true; });
        map.classList.add('has-dim');
      }
      mark(current, false);
    }

    renderPanel(pinned);
    draw();
    if (o.highlight) setHighlight(o.highlight);
    var ro = null;
    if (window.ResizeObserver) { ro = new ResizeObserver(function () { draw(); }); ro.observe(lanesEl); }
    else window.addEventListener('resize', draw);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(draw);

    return {
      update: function (opts) {
        if (opts && 'highlight' in opts) setHighlight(opts.highlight);
      },
      select: function (id) { if (clips[id]) pin(id, false); },
      destroy: function () {
        if (ro) ro.disconnect(); else window.removeEventListener('resize', draw);
        map.removeEventListener('click', onClick);
      }
    };
  }

  window.ClaimTraceGraph = { mount: mount };

  /* A map rendered at build time names its data and the clause it opens on; mount it once that data loads.
     Without it (no scripting, or the fetch fails) the lanes, the panel and the list of links still show. */
  var auto = document.querySelectorAll('[data-map][data-graph-src]');
  if (!auto.length || !window.fetch) return;
  Array.prototype.forEach.call(auto, function (host) {
    fetch(host.ownerDocument.baseURI.replace(/[#?].*$/, '').replace(/[^/]*$/, '') + host.getAttribute('data-graph-src'))
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        mount(host, data, { selected: host.getAttribute('data-graph-selected') || undefined });
      })
      .catch(function () { /* the static map stays: lanes, the first clause and the list of links */ });
  });
})();
