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
      frag.appendChild(el('blockquote', 'map__quote', c.text));
      var file = el('p', 'map__file', 'Verbatim from ');
      file.appendChild(el('span', 'num', lane.file));
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

    /* ---- wires ---- */
    function draw() {
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      wires = [];
      if (getComputedStyle(svg).display === 'none') { mark(current, false); return; }
      var box = lanesEl.getBoundingClientRect();
      data.links.forEach(function (l) {
        var a = byId[l.from], b = byId[l.to];
        if (!a || !b) return;
        var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
        var down = ra.top > rb.top; // the source sits on a lower lane: leave from its top, arrive at the target's foot
        var x1 = ra.left + ra.width / 2 - box.left, x2 = rb.left + rb.width / 2 - box.left;
        var y1 = (down ? ra.top : ra.bottom) - box.top, y2 = (down ? rb.bottom : rb.top) - box.top;
        var my = (y1 + y2) / 2;
        var p = document.createElementNS(NS, 'path');
        p.setAttribute('d', 'M' + x1 + ' ' + y1 + ' C' + x1 + ' ' + my + ' ' + x2 + ' ' + my + ' ' + x2 + ' ' + y2);
        p.setAttribute('class', 'wire wire--' + l.kind);
        svg.appendChild(p);
        wires.push({ link: l, path: p });
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
