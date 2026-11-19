#!/usr/bin/env python3
"""Synthesize the film's soundtrack: a soft pad bed, a tick per typed character, a low hit on the strike.

Standard library only, deterministic (seeded). Writes audio/score.wav (48 kHz, 16-bit stereo), which video.html
mixes in through <audio id="score">. Times below must match the choreography in video.html.

    python3 make_audio.py
"""
from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path

RATE = 48_000
DURATION = 50.3
N = int(RATE * DURATION)
OUT = Path(__file__).resolve().parent / "audio" / "score.wav"

# Typing, as in video.html: data-type chars per second and data-type-delay (video seconds).
QUESTION = ("Did the amendment change the deadline?", 1.0, 14.0)
ANSWER = ("Yes. Amendment No. 1 §1.1 moved it from March 31, 2026 to May 15, 2026.", 34.6, 30.0)
STRIKE = 12.3                       # "March 31, 2026" struck
SOFT_HITS = [(20.2, 0.32), (26.4, 0.32)]   # the two contradictions, quieter than the strike
CHIME = 40.0                        # "23 of 23 quotes match the source text"

left = [0.0] * N
right = [0.0] * N


def add(buf: list[float], start: float, samples: list[float], gain: float = 1.0) -> None:
    i0 = int(start * RATE)
    for j, v in enumerate(samples):
        i = i0 + j
        if 0 <= i < N:
            buf[i] += v * gain


def pad() -> None:
    """A slow D-major-add9 bed with breathing voices and a little air."""
    voices = [(73.42, 0.050), (110.0, 0.060), (146.83, 0.055), (185.0, 0.040), (220.0, 0.040), (329.63, 0.022)]
    rng = random.Random(7)
    two_pi = 2 * math.pi
    params = [(f, a, rng.uniform(0.04, 0.11), rng.uniform(0, two_pi), rng.uniform(0.6, 1.4)) for f, a in voices]
    noise_l = noise_r = 0.0
    for i in range(N):
        t = i / RATE
        env = min(1.0, t / 3.0) * min(1.0, max(0.0, (DURATION - t) / 4.0))
        swell = 0.85 + 0.15 * math.sin(two_pi * t / 26.0 - 1.2)
        l = r = 0.0
        for f, a, lfo, ph, det in params:
            amp = a * (0.7 + 0.3 * math.sin(two_pi * lfo * t + ph))
            l += amp * math.sin(two_pi * (f - det * 0.12) * t + ph)
            r += amp * math.sin(two_pi * (f + det * 0.12) * t + ph * 1.3)
        # air: one-pole low-passed noise
        noise_l += 0.02 * (rng.uniform(-1, 1) - noise_l)
        noise_r += 0.02 * (rng.uniform(-1, 1) - noise_r)
        left[i] += env * swell * (l + 0.10 * noise_l)
        right[i] += env * swell * (r + 0.10 * noise_r)


def tick(rng: random.Random) -> list[float]:
    """A short soft key tick: a damped high sine with a breath of noise."""
    n = int(0.035 * RATE)
    f = rng.uniform(2600, 3300)
    out = []
    for j in range(n):
        t = j / RATE
        e = math.exp(-t / 0.006)
        out.append(e * (0.7 * math.sin(2 * math.pi * f * t) + 0.3 * rng.uniform(-1, 1)))
    return out


def low_hit(gain: float = 1.0) -> list[float]:
    """A low hit: a sine sweeping 92 -> 46 Hz with a long tail, plus a short low-passed thump."""
    n = int(1.6 * RATE)
    out, phase, lp = [], 0.0, 0.0
    rng = random.Random(11)
    for j in range(n):
        t = j / RATE
        f = 46 + 46 * math.exp(-t / 0.08)
        phase += 2 * math.pi * f / RATE
        body = math.exp(-t / 0.45) * math.sin(phase)
        lp += 0.08 * (rng.uniform(-1, 1) - lp)
        thump = math.exp(-t / 0.03) * lp * 3.0
        attack = min(1.0, t / 0.004)
        out.append(gain * attack * (0.9 * body + 0.35 * thump))
    return out


def chime() -> list[float]:
    """A quiet two-note bell (A5, E6) for the verified line."""
    n = int(1.8 * RATE)
    out = []
    for j in range(n):
        t = j / RATE
        e = math.exp(-t / 0.5) * min(1.0, t / 0.01)
        out.append(e * (0.6 * math.sin(2 * math.pi * 880 * t) + 0.4 * math.sin(2 * math.pi * 1318.5 * t)))
    return out


def typing(text: str, delay: float, cps: float, rng: random.Random) -> None:
    for i, ch in enumerate(text):
        if ch.isspace():
            continue
        t = delay + i / cps
        s = tick(rng)
        g = rng.uniform(0.10, 0.14)
        add(left, t, s, g * rng.uniform(0.85, 1.0))
        add(right, t, s, g * rng.uniform(0.85, 1.0))


def main() -> None:
    pad()
    rng = random.Random(3)
    typing(*QUESTION, rng)
    typing(*ANSWER, rng)
    hit = low_hit()
    add(left, STRIKE, hit, 0.75)
    add(right, STRIKE, hit, 0.75)
    for t, g in SOFT_HITS:
        s = low_hit(g)
        add(left, t, s, 0.75)
        add(right, t, s, 0.75)
    c = chime()
    add(left, CHIME, c, 0.06)
    add(right, CHIME, c, 0.06)

    peak = max(max(abs(v) for v in left), max(abs(v) for v in right))
    scale = 0.89 / peak if peak > 0.89 else 1.0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        frames = bytearray()
        for l, r in zip(left, right):
            frames += struct.pack("<hh", int(max(-1, min(1, l * scale)) * 32767), int(max(-1, min(1, r * scale)) * 32767))
        w.writeframes(bytes(frames))
    print(f"wrote {OUT} ({DURATION:.0f} s, peak {peak:.2f}, scale {scale:.2f})")


if __name__ == "__main__":
    main()
