/* The evidence map on the home page: lanes of clause buttons (rendered at build time by
   scripts/build_site_data.py), connectors drawn here from data/samples.json, and a side panel that shows the
   clause in focus. Without scripting the lanes, the panel (clause 2.1) and the full list of links still show.
   Keyboard: one tab stop; arrow keys move along a lane and between lanes, Home and End jump within a lane. */
(function () {
  'use strict';
  var map = document.querySelector('[data-map]');
  if (!map || !window.fetch) return;
  var lanesEl = map.querySelector('[data-map-lanes]');
  var svg = map.querySelector('.map__wires');
  var panel = document.getElementById('map-panel');
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  var NS = 'http://www.w3.org/2000/svg';

  var STATUS = {
    replaces: ['Replaced', 'i-replaced'], changes: ['Changed', 'i-replaced'], contradicts: ['Contradicted', 'i-contradicts'],
    partly: ['Partly supported', 'i-partly'], supports: ['Supported', 'i-supports'], review: ['Needs review', 'i-review']
  };
  var STATE = { replaced: ['Replaced', 'i-replaced'], in_force: ['In force', 'i-inforce'], evidence: ['Evidence', 'i-evidence'] };

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

  fetch(map.ownerDocument.baseURI.replace(/[#?].*$/, '').replace(/[^/]*$/, '') + 'data/samples.json')
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(start)
    .catch(function () { /* the static map stays: lanes, clause 2.1 and the list of links */ });

  function start(data) {
    var clips = {}, laneOf = {}, laneNames = {};
    data.lanes.forEach(function (lane) {
      laneNames[lane.key] = lane;
      lane.clips.forEach(function (c) { clips[c.id] = c; laneOf[c.id] = lane; });
    });
    var buttons = Array.prototype.slice.call(map.querySelectorAll('[data-clip]'));
    var byId = {};
    buttons.forEach(function (b) { byId[b.dataset.clip] = b; });
    var rows = Array.prototype.slice.call(map.querySelectorAll('.lane')).map(function (lane) {
      return Array.prototype.slice.call(lane.querySelectorAll('[data-clip]'));
    });
    var pinned = 'msa-2.1';
    var wires = [];

    function cite(id) { return laneOf[id].name + ' §' + clips[id].section; }
    function linksOf(id) { return data.links.filter(function (l) { return l.to === id || l.from === id; }); }

    /* ---- panel ---- */
    function renderPanel(id) {
      var c = clips[id], lane = laneOf[id], st = STATE[c.effect] || STATE.evidence;
      var frag = document.createDocumentFragment();
      var where = el('p', 'map__where');
      where.appendChild(el('span', 'map__doc', lane.name));
      where.appendChild(document.createTextNode(' '));
      where.appendChild(el('span', 'num map__sec', '§' + c.section));
      frag.appendChild(where);
      frag.appendChild(el('p', 'map__heading', c.heading || ''));
      var state = el('p', 'map__state map__state--' + c.effect.replace('_', '-'));
      state.appendChild(icon(st[1]));
      state.appendChild(document.createTextNode(st[0]));
      frag.appendChild(state);
      var file;
      if (c.withheld) {
        file = el('p', 'map__file', 'Wording not shown on this page. Read it on ');
        var go = el('a', '', 'Try it');
        go.href = 'try/';
        file.appendChild(go);
        file.appendChild(document.createTextNode(', where the full sample contract is loaded.'));
      } else {
        frag.appendChild(el('blockquote', 'map__quote', c.text));
        file = el('p', 'map__file', 'Verbatim from ');
        file.appendChild(el('span', 'num', lane.file));
      }
      frag.appendChild(file);
      frag.appendChild(el('h3', 'map__links-title', 'Links'));
      var ls = linksOf(id);
      if (!ls.length) {
        frag.appendChild(el('p', 'map__none', 'Nothing in the other documents links to this clause.'));
      } else {
        var ul = el('ul', 'map__links');
        ls.forEach(function (l) {
          var incoming = l.to === id, other = incoming ? l.from : l.to;
          var li = el('li', 'map__link');
          var s = el('span', 'status status--' + l.kind);
          s.appendChild(icon(STATUS[l.kind][1]));
          s.appendChild(document.createTextNode(STATUS[l.kind][0]));
          li.appendChild(s);
          var t = el('span', 'map__link-text', data.kinds[l.kind][incoming ? 'in' : 'out'] + ' ');
          var b = el('button', 'cite', cite(other));
          b.type = 'button';
          b.dataset.go = other;
          t.appendChild(b);
          if (l.note) t.appendChild(el('span', 'map__note', l.note));
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
    var laneEls = Array.prototype.slice.call(map.querySelectorAll('.lane'));
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
      if (getComputedStyle(svg).display === 'none') { mark(current, false); return; }
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
        var p = document.createElementNS(NS, 'path');
        p.setAttribute('d', rounded(r.pts, 10));
        p.setAttribute('class', 'wire wire--' + r.link.kind);
        svg.appendChild(p);
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
      });
      wires.forEach(function (w) {
        var on = w.link.to === id || w.link.from === id;
        w.path.classList.toggle('is-active', on);
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
    function pin(id, animate) {
      pinned = id;
      buttons.forEach(function (b) { b.tabIndex = b.dataset.clip === id ? 0 : -1; });
      show(id, animate);
    }

    /* roving tab stop */
    buttons.forEach(function (b) { b.tabIndex = b.dataset.clip === pinned ? 0 : -1; });

    map.addEventListener('click', function (e) {
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
      if (window.matchMedia('(max-width: 75rem)').matches) {
        var r = panel.getBoundingClientRect();
        if (r.top > window.innerHeight || r.bottom < 0) panel.scrollIntoView({ block: 'nearest', behavior: reduce.matches ? 'auto' : 'smooth' });
      }
    });
    lanesEl.addEventListener('focusin', function (e) {
      var b = e.target.closest('[data-clip]');
      if (b && b.dataset.clip !== pinned) pin(b.dataset.clip, true);
    });
    lanesEl.addEventListener('pointerover', function (e) {
      if (e.pointerType !== 'mouse') return;
      var b = e.target.closest('[data-clip]');
      if (b) show(b.dataset.clip, true);
    });
    lanesEl.addEventListener('pointerleave', function () { show(pinned, false); });

    lanesEl.addEventListener('keydown', function (e) {
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
        if (to) {
          var cx = b.getBoundingClientRect().left + b.offsetWidth / 2, best = null, bd = Infinity;
          to.forEach(function (c) { var d = Math.abs(c.getBoundingClientRect().left + c.offsetWidth / 2 - cx); if (d < bd) { bd = d; best = c; } });
          next = best;
        } else next = b;
      } else return;
      e.preventDefault();
      if (next) next.focus();
    });

    renderPanel(pinned);
    draw();
    if (window.ResizeObserver) new ResizeObserver(function () { draw(); }).observe(lanesEl);
    else window.addEventListener('resize', draw);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(draw);
  }
})();
