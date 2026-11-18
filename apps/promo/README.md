# ClaimTrace promo film

A 54-second, one-take promo (1920×1080, 30 fps) built with [Remotion](https://www.remotion.dev). One virtual
camera moves through one large canvas: contract → amendment → delivery record → ClaimTrace register →
a typed question → an answer made of quotes → three cross-document conflicts → closing title.

Output: `apps/site/media/claimtrace-promo.mp4` (with music bed), `apps/site/media/claimtrace-promo.jpg` (poster)
and `apps/promo/out/claimtrace-promo-sfx-only.mp4` (sound effects only, not committed).

## What is real

- Every UI image in `public/shots/` is a screenshot of the actual app (dark colour scheme, device scale 2),
  taken by `scripts/capture.cjs` after **Load sample documents**. Nothing in them is mocked up.
- The paper documents are excerpts of `examples/documents/*.md`, reproduced word for word (some clauses omitted).
- The findings shown (7 days late, United Kingdom vs Ireland, 99.1% vs 99.5%) are what the app reports for the
  sample documents; see `examples/outputs/`. The sample documents are fictional.
- Overlays drawn in the film: the typed question and caret, the focus ring, the enabled Ask button, highlight
  outlines, captions, callout badges and the accent "trace" line. Colours and fonts come from
  `apps/web/src/styles.css` (the app uses the system UI font, which is Inter on the capture machine).

## Rebuild

```bash
# 1. Screenshots (needs the app running with an empty database and Playwright installed)
CLAIMTRACE_DB=/tmp/ct-promo.db claimtrace serve --port 8791 &
BASE=http://127.0.0.1:8791 npm run capture

# 2. Sound: every sound is synthesised with numpy (pad bed, riser, impacts, key clicks, chime). Deterministic.
npm run audio            # writes public/audio/*.wav (not committed)

# 3. Preview / render
npm install
npm run studio
# Offline machines: point Remotion at an installed headless Chromium instead of downloading one
export REMOTION_BROWSER_EXECUTABLE=/opt/pw-browsers/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell
python3 scripts/finish.py   # master render, SFX-only audio, x264 2-pass (~1.45 Mbit/s), loudnorm -16 LUFS, poster
```

The composition takes one input prop, `bgm` (default `true`). `--props='{"bgm":false}'` drops the music bed and
keeps every sound effect, for anyone who wants to score the film themselves.

All timing lives in `src/timeline.ts` (camera keyframes, typing schedule, sound placements, world layout).
Rendering is deterministic: no `Math.random()` or `Date.now()`; the typing rhythm uses a fixed integer hash.

## Licence note

Remotion is not MIT-licensed. It is free for individuals and companies with up to three employees, and for
non-profits; larger companies need a company licence. See
<https://github.com/remotion-dev/remotion/blob/main/LICENSE.md>. The film itself and the scripts in this folder
are part of ClaimTrace and follow the repository's licence.
