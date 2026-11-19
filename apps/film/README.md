# ClaimTrace film (v0.4)

A 50.3 s, 1920x1080, 30 fps one-take film made with [givemotion](https://www.npmjs.com/package/givemotion) 0.1.6. It
uses the site's own design system: `site` is a symlink to `../site`, so `video.html` loads `site/tokens.css` and
`site/fonts.css` (self-hosted Instrument Sans, Figtree and JetBrains Mono woff2 in `apps/site/fonts/`). Every quote
is verbatim from `apps/site/data/samples.json` (the rules engine on `examples/documents`).

Output: `apps/site/media/claimtrace-film.mp4` and the poster `apps/site/media/claimtrace-film-poster.jpg`.

## Files

- `video.html`: the composition. The DIRECTION block and SHOT LIST at the top say what each second does; the
  script below lays out the world (lanes, clips, connectors), the camera shots and the choreography.
- `make_audio.py`: synthesizes the soundtrack (pad bed, a tick per typed character, a low hit on the strike) with
  the Python standard library into `audio/score.wav` (not committed). Its times mirror the choreography.
- `brief.md`: the beats with their times, read by `givemotion review`.

## Re-render

```sh
cd apps/film
python3 make_audio.py                                   # writes audio/score.wav
npx givemotion@0.1.6 check video.html                   # expect 0 errors, 0 warnings
npx givemotion@0.1.6 review video.html                  # optional: review/ with frames and REVIEW.md
npx givemotion@0.1.6 render video.html -o out/film.mp4 --motion-blur auto --quality high
ffmpeg -y -i out/film.mp4 -c:v libx264 -preset slow -crf 22 -tune animation -pix_fmt yuv420p -c:a aac -b:a 128k \
  -movflags +faststart ../site/media/claimtrace-film.mp4
ffmpeg -y -ss 43.5 -i ../site/media/claimtrace-film.mp4 -frames:v 1 -q:v 3 ../site/media/claimtrace-film-poster.jpg
```

If you change a time in `video.html`, change it in `make_audio.py` (and `brief.md`) too. `out/`, `review/`,
`audio/*.wav` and render caches are ignored by git.
