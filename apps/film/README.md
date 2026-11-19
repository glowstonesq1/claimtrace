# ClaimTrace film

The source of the 50-second film on the website (1920x1080, 30 fps, one continuous take). Every quote in it is
verbatim from `apps/site/data/samples.json`, the rules engine's output on `examples/documents`.

Output: `apps/site/media/claimtrace-film.mp4` and its poster `apps/site/media/claimtrace-film-poster.jpg`.

## Files

- `video.html`: the composition. The shot list at the top gives each beat's time.
- `make_audio.py`: synthesizes the soundtrack into `audio/score.wav` (not committed) with the Python standard
  library. Its times mirror the shot list; if you change a time in one, change it in the other.
- `site`: a symlink to `../site`, so the film uses the site's tokens and self-hosted fonts.

## Re-render

Needs Node 20+ and ffmpeg. The composition is rendered with [givemotion](https://www.npmjs.com/package/givemotion)
0.1.6.

```sh
cd apps/film
python3 make_audio.py
npx givemotion@0.1.6 render video.html -o out/film.mp4 --motion-blur auto --quality high
ffmpeg -y -i out/film.mp4 -c:v libx264 -preset slow -crf 22 -tune animation -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart \
  ../site/media/claimtrace-film.mp4
ffmpeg -y -ss 43.5 -i ../site/media/claimtrace-film.mp4 -frames:v 1 -q:v 3 ../site/media/claimtrace-film-poster.jpg
```

On Windows, clone with symlinks enabled (`git clone -c core.symlinks=true ...`); otherwise `site` checks out as a
text file and the film loads no tokens or fonts. `out/` and `audio/*.wav` are ignored by git.
