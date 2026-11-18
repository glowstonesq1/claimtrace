"""Final delivery: one video encode, two loudness-normalised audio mixes, poster frame.

Run from apps/promo after `npm run audio`:
  python3 scripts/finish.py
Steps:
  1. Remotion renders a near-lossless master (video + music bed mix) and an SFX-only WAV (bgm=false).
  2. ffmpeg encodes the video once (2-pass x264, ~1.45 Mbit/s, keeps the film under ~12 MB).
  3. Each audio mix is normalised to -16 LUFS / -1.5 dBTP with two-pass loudnorm and muxed with that video.
  4. Poster frame from the closing title.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"  # dev-only render helper

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
SITE = ROOT.parent / "site" / "media"
OUT.mkdir(exist_ok=True)
SITE.mkdir(parents=True, exist_ok=True)
COMP = "ClaimTracePromo"
POSTER_FRAME = 1560
VIDEO_KBPS = 1450


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=True, cwd=ROOT, **kw)


def remotion(*args: str) -> None:
    run(["npx", "remotion", *args])


def loudnorm(src: Path, dst: Path) -> None:
    target = "I=-16:TP=-1.5:LRA=11"
    p = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(src), "-af", f"loudnorm={target}:print_format=json", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    m = json.loads(re.findall(r"\{[^{}]+\}", p.stderr)[-1])
    af = (
        f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
        f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true"
    )
    run([FFMPEG, "-v", "error", "-y", "-i", str(src), "-af", af, "-ar", "48000", str(dst)])


def main() -> None:
    remotion(
        "render",
        "src/index.ts",
        COMP,
        "out/master-bgm.mp4",
        "--codec=h264",
        "--crf=12",
        "--x264-preset=veryfast",
        '--props={"bgm":true}',
    )
    remotion("render", "src/index.ts", COMP, "out/audio-sfx.wav", "--codec=wav", '--props={"bgm":false}')
    run([FFMPEG, "-v", "error", "-y", "-i", "out/master-bgm.mp4", "-vn", "-c:a", "pcm_s16le", "out/audio-bgm.wav"])

    common = [
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-tune",
        "animation",
        "-b:v",
        f"{VIDEO_KBPS}k",
        "-maxrate",
        "4000k",
        "-bufsize",
        "8000k",
        "-pix_fmt",
        "yuv420p",
        "-passlogfile",
        "out/x264pass",
    ]
    run([FFMPEG, "-v", "error", "-y", "-i", "out/master-bgm.mp4", *common, "-pass", "1", "-f", "mp4", os.devnull])
    run([FFMPEG, "-v", "error", "-y", "-i", "out/master-bgm.mp4", *common, "-profile:v", "high", "-pass", "2", "out/video.mp4"])

    for name, dst in (("bgm", SITE / "claimtrace-promo.mp4"), ("sfx", OUT / "claimtrace-promo-sfx-only.mp4")):
        loudnorm(OUT / f"audio-{name}.wav", OUT / f"audio-{name}-norm.wav")
        run(
            [
                FFMPEG,
                "-v",
                "error",
                "-y",
                "-i",
                "out/video.mp4",
                "-i",
                f"out/audio-{name}-norm.wav",
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(dst),
            ]
        )

    remotion(
        "still",
        "src/index.ts",
        COMP,
        str(SITE / "claimtrace-promo.jpg"),
        f"--frame={POSTER_FRAME}",
        "--image-format=jpeg",
        "--jpeg-quality=86",
    )
    for f in (SITE / "claimtrace-promo.mp4", OUT / "claimtrace-promo-sfx-only.mp4", SITE / "claimtrace-promo.jpg"):
        print(f"{f.relative_to(ROOT.parent.parent)}  {f.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
