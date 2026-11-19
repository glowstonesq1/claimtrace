# Figure frames

The README and docs images (`docs/img/readme-*.png`) are real site UI, captured at 2x and set in frames
that use the site's own tokens and fonts (`apps/site/tokens.css`, `apps/site/fonts.css`): the evening sky and
smoked glass of the home hero.

| File | What it shows |
|---|---|
| `readme-hero.png` | The home page's first screen |
| `readme-map.png` | The evidence map, contract clause 2.1 selected |
| `readme-try.png` | /try with the four samples loaded and the contract checked against the delivery record |
| `readme-evidence.png` | The four plain answers on /evidence |

## Regenerate

Needs Node with Playwright, and the /try engine bundle (`python scripts/build_try_bundle.py`).

```bash
python scripts/inject_partials.py                                   # if the pages' nav and footer are stale
python -m http.server 8790 --bind 127.0.0.1 -d apps/site &          # the site
python -m http.server 8791 --bind 127.0.0.1 &                       # the repository root, for frame.html
node docs/img/frames/capture.mjs                                    # real UI at 2x into docs/img/frames/raw/
node docs/img/frames/render.mjs                                     # frames at 2x into docs/img/readme-*.png
pip install imagequant pyoxipng && python docs/img/frames/optimise.py   # 256-colour palette, then oxipng
```

- `capture.mjs` drives the real pages: it selects clause 2.1 on the map, loads the samples on /try and runs
  the contract against the delivery record.
- `frames.js` holds each frame's title, note and crop (in CSS pixels of the capture). `frame.html?f=map`
  shows one frame in a browser.
- `raw/` is not committed. Keep each PNG under about 600 KB.
