/* ClaimTrace site: film fallback, copy buttons, the home page's tabs and glyph field, and one GSAP entrance.
   Everything here is progressive: with scripting off or reduced motion the page is already complete. */
(function () {
  'use strict';

  /* 1. The film slot. If the film fails to load, show its poster instead of an empty player. */
  document.querySelectorAll('[data-film]').forEach(function (frame) {
    var video = frame.querySelector('video');
    if (!video) return;
    var source = video.querySelector('source');
    var missing = function () { frame.classList.add('is-missing'); video.setAttribute('aria-hidden', 'true'); video.setAttribute('tabindex', '-1'); };
    if (source) source.addEventListener('error', missing, { once: true });
    video.addEventListener('error', missing, { once: true });
    if (video.networkState === 3) missing(); // NETWORK_NO_SOURCE
    var poster = video.getAttribute('poster');
    if (poster) {
      var probe = new Image();
      probe.onerror = function () { video.removeAttribute('poster'); };
      probe.src = poster;
    }
  });

  /* 2. Copy buttons for commands (.cmd). Added here, so a page without scripting shows no dead control.
        The label swaps to "Copied" and the page's status region announces it to screen readers. */
  var status = document.querySelector('[data-copy-status]');
  var announce = function (msg) {
    if (!status) return;
    status.textContent = '';
    window.setTimeout(function () { status.textContent = msg; }, 50);
  };
  var copyText = function (text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise(function (resolve, reject) {
      var area = document.createElement('textarea');
      area.value = text;
      area.setAttribute('readonly', '');
      area.className = 'visually-hidden';
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      area.remove();
      if (ok) { resolve(); } else { reject(new Error('copy failed')); }
    });
  };
  document.querySelectorAll('.cmd').forEach(function (block, i) {
    var code = block.querySelector('pre');
    if (!code) return;
    var button = document.createElement('button');
    var id = 'cmd-' + (i + 1);
    code.id = code.id || id;
    button.type = 'button';
    button.className = 'copy';
    button.textContent = 'Copy';
    button.setAttribute('aria-describedby', code.id);
    var timer = null;
    button.addEventListener('click', function () {
      copyText(code.textContent.replace(/\s+$/, '')).then(function () {
        button.textContent = 'Copied';
        button.dataset.state = 'done';
        announce('Copied to the clipboard');
      }, function () {
        button.textContent = 'Select and copy';
        announce('Could not copy. Select the text and copy it yourself.');
      });
      window.clearTimeout(timer);
      timer = window.setTimeout(function () { button.textContent = 'Copy'; delete button.dataset.state; }, 2500);
    });
    block.appendChild(button);
  });

  /* 3. Tabs (home, "Three ways to run it"). Without scripting all three panels show, stacked. */
  document.querySelectorAll('[data-tabs]').forEach(function (box) {
    var tabs = Array.prototype.slice.call(box.querySelectorAll('[role="tab"]'));
    var select = function (tab, focus) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute('aria-selected', on ? 'true' : 'false');
        t.tabIndex = on ? 0 : -1;
        var p = document.getElementById(t.getAttribute('aria-controls'));
        if (p) p.hidden = !on;
      });
      if (focus) tab.focus();
    };
    tabs.forEach(function (t, i) {
      t.addEventListener('click', function () { select(t, false); });
      t.addEventListener('keydown', function (e) {
        var n = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
        if (n === undefined) return;
        e.preventDefault();
        select(tabs[(n + tabs.length) % tabs.length], true);
      });
    });
    var start = tabs.filter(function (t) { return t.getAttribute('aria-selected') === 'true'; })[0] || tabs[0];
    if (start) select(start, false);
  });

  /* 4. The hero's glyph field: the sample contract's own words, faint, under the sky. The two delivery dates
        are picked out (the struck one in apricot, the one in force in periwinkle). Decorative: aria-hidden. */
  var field = document.querySelector('[data-field]');
  if (field && window.fetch) {
    fetch(new URL('data/samples.json', document.baseURI)).then(function (r) { return r.ok ? r.json() : null; }).then(function (data) {
      if (!data) return;
      var rows = data.hero && data.hero.rows || [];
      var lead = rows[0] && rows[0].change;
      var words = data.lanes.map(function (l) { return l.clips.map(function (c) { return c.section + ' ' + c.text; }).join(' '); }).join(' ');
      var text = (words + ' ').repeat(3);
      field.textContent = '';
      if (!lead) { field.textContent = text; return; }
      var re = new RegExp('(' + [lead.old, lead.new].map(function (s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }).join('|') + ')', 'g');
      text.split(re).forEach(function (part) {
        if (part === lead.old || part === lead.new) {
          var s = document.createElement('span');
          s.className = part === lead.old ? 'hi' : 'lo';
          s.textContent = part;
          field.appendChild(s);
        } else field.appendChild(document.createTextNode(part));
      });
    }).catch(function () {});
  }

  /* 5. Motion: with GSAP loaded and motion allowed, the hero rows rise in once. Visible by default. */
  var gsap = window.gsap;
  if (!gsap) return;
  gsap.matchMedia().add('(prefers-reduced-motion: no-preference)', function () {
    var rows = document.querySelectorAll('.ledger__row');
    if (!rows.length) return;
    gsap.from(rows, { opacity: 0, y: 10, duration: 0.6, ease: 'power3.out', stagger: 0.07, delay: 0.15, clearProps: 'all' });
  });
})();
