/* ClaimTrace site: film fallback, plus two GSAP scroll patterns (word scrub on the promise, sticky walk-through).
   Everything here is progressive: with scripting off or reduced motion the page is already complete. */
(function () {
  'use strict';

  /* 1. The film slot. Until media/claimtrace-promo.mp4 exists, show the screenshot instead of an empty player. */
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

  /* 2. Motion: only with GSAP loaded and motion allowed. */
  var gsap = window.gsap;
  var ScrollTrigger = window.ScrollTrigger;
  if (!gsap || !ScrollTrigger) return;
  gsap.registerPlugin(ScrollTrigger);

  var mm = gsap.matchMedia();

  /* Pattern A: the promise head reads in, word by word, as it scrolls through (scrubbed). */
  mm.add('(prefers-reduced-motion: no-preference)', function () {
    var head = document.querySelector('[data-scrub]');
    if (!head) return;
    var original = head.textContent;
    head.setAttribute('aria-label', original);
    head.innerHTML = original.split(/(\s+)/).map(function (part) {
      return /^\s+$/.test(part) ? part : '<span class="w" aria-hidden="true">' + part + '</span>';
    }).join('');
    gsap.fromTo(head.querySelectorAll('.w'), { opacity: 0.15 }, {
      opacity: 1, ease: 'none', stagger: 0.12,
      scrollTrigger: { trigger: head, start: 'top 85%', end: 'bottom 45%', scrub: true }
    });
    return function () { head.textContent = original; head.removeAttribute('aria-label'); };
  });

  /* Pattern B: register, ask, verify. One screen stays put while the three steps scroll past it. */
  mm.add('(prefers-reduced-motion: no-preference) and (min-width: 60rem)', function () {
    var walk = document.querySelector('[data-walk]');
    if (!walk) return;
    var texts = Array.prototype.slice.call(walk.querySelectorAll('.walk__text'));
    var figs = Array.prototype.slice.call(walk.querySelectorAll('.walk__fig'));
    walk.classList.add('is-pinned');
    gsap.set(figs, { autoAlpha: 0, y: 12 });
    gsap.set(figs[0], { autoAlpha: 1, y: 0 });
    gsap.set(texts.slice(1), { opacity: 0.35 });
    var current = 0;
    var show = function (i) {
      if (i === current) return;
      gsap.to(figs[current], { autoAlpha: 0, y: -12, duration: 0.35, ease: 'power2.in', overwrite: true });
      gsap.fromTo(figs[i], { autoAlpha: 0, y: 12 }, { autoAlpha: 1, y: 0, duration: 0.45, ease: 'power3.out', overwrite: true });
      gsap.to(texts, { opacity: function (k) { return k === i ? 1 : 0.35; }, duration: 0.3, overwrite: true });
      current = i;
    };
    texts.forEach(function (t, i) {
      ScrollTrigger.create({
        trigger: t, start: 'top 55%', end: 'bottom 55%',
        onToggle: function (self) { if (self.isActive) show(i); }
      });
    });
    ScrollTrigger.refresh();
    return function () {
      walk.classList.remove('is-pinned');
      gsap.set(figs.concat(texts), { clearProps: 'all' });
    };
  });
})();
