"""Synthesises every sound in the promo (no samples, no downloads). Deterministic: fixed RNG seeds.

Usage: python3 scripts/make_audio.py public/audio
Writes 48 kHz 16-bit WAVs: bed (music), riser, impact, hit (reveal), whoosh, key1-3, enter, mark, chime.
"""

import sys
import wave
from pathlib import Path

import numpy as np

SR = 48000
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "public/audio")
OUT.mkdir(parents=True, exist_ok=True)


def rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def t_axis(sec: float) -> np.ndarray:
    return np.arange(int(sec * SR)) / SR


def onepole_lp(x: np.ndarray, cutoff) -> np.ndarray:
    """One-pole low-pass; cutoff may be a scalar or a per-sample array (Hz)."""
    c = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    a = np.exp(-2 * np.pi * c / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1 - a[i]) * x[i] + a[i] * acc
        y[i] = acc
    return y


def lp_fast(x: np.ndarray, cutoff: float, order: int = 2) -> np.ndarray:
    """Static low-pass via FFT brick-ish rolloff (fast for long signals)."""
    n = len(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    h = 1 / np.sqrt(1 + (f / cutoff) ** (2 * order))
    return np.fft.irfft(np.fft.rfft(x) * h, n)


def hp_fast(x: np.ndarray, cutoff: float, order: int = 2) -> np.ndarray:
    n = len(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    h = 1 / np.sqrt(1 + (cutoff / np.maximum(f, 1e-3)) ** (2 * order))
    return np.fft.irfft(np.fft.rfft(x) * h, n)


def reverb(x: np.ndarray, seconds: float, mix: float, seed: int) -> np.ndarray:
    ir_t = t_axis(seconds)
    ir = rng(seed).standard_normal(len(ir_t)) * np.exp(-ir_t * 6.0 / seconds)
    ir = lp_fast(ir, 5000)
    ir /= np.sqrt(np.sum(ir**2)) + 1e-9
    n = len(x) + len(ir)
    wet = np.fft.irfft(np.fft.rfft(x, n) * np.fft.rfft(ir, n), n)
    dry = np.concatenate([x, np.zeros(len(ir))])
    return (1 - mix) * dry + mix * wet * 0.6


def save(name: str, x: np.ndarray, peak: float = 0.89, stereo_width: float = 0.0, seed: int = 0) -> None:
    x = np.asarray(x, dtype=float)
    if x.ndim == 1:
        if stereo_width > 0:
            # decorrelate slightly with a tiny delay for width
            d = int(0.011 * SR)
            r = np.concatenate([np.zeros(d), x[:-d]])
            x = np.stack([x, (1 - stereo_width) * x + stereo_width * r], axis=1)
        else:
            x = np.stack([x, x], axis=1)
    m = np.max(np.abs(x)) + 1e-9
    x = x / m * peak
    pcm = (x * 32767).astype(np.int16)
    with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"{name}.wav  {len(x) / SR:.2f}s")


def fade(x: np.ndarray, fin: float, fout: float) -> np.ndarray:
    n = len(x)
    env = np.ones(n)
    a, b = int(fin * SR), int(fout * SR)
    if a:
        env[:a] = np.linspace(0, 1, a) ** 2
    if b:
        env[-b:] = np.linspace(1, 0, b) ** 2
    return x * env


def note(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


# ---------------------------------------------------------------- bed (music)
def make_bed(total: float = 56.0) -> np.ndarray:
    t = t_axis(total)
    # A minor-ish ambient progression; each chord ~6.75 s with long crossfades.
    chords = [
        [45, 52, 57, 60, 64],  # Am
        [41, 48, 53, 57, 60],  # F
        [43, 50, 55, 59, 62],  # G
        [45, 52, 57, 60, 64],  # Am
        [41, 48, 53, 57, 64],  # Fmaj7-ish
        [36, 48, 55, 60, 64],  # C
        [43, 50, 55, 59, 62],  # G
        [45, 52, 57, 60, 64],  # Am (title)
    ]
    seg = total / len(chords)
    left = np.zeros_like(t)
    right = np.zeros_like(t)
    r = rng(7)
    for ci, ch in enumerate(chords):
        start = ci * seg - 1.5
        env = np.clip((t - start) / 2.5, 0, 1) * np.clip((start + seg + 3.0 - t) / 2.5, 0, 1)
        env = np.sin(env * np.pi / 2) ** 2
        for ni, m in enumerate(ch):
            f = note(m)
            for det, pan in ((-0.07, 0.25), (0.0, 0.5), (0.08, 0.75)):
                ff = f * 2 ** (det / 12)
                ph = r.uniform(0, 2 * np.pi)
                # soft saw: a few harmonics, falling fast
                v = sum(np.sin(2 * np.pi * ff * k * t + ph * k) / (k**1.6) for k in range(1, 6))
                g = 0.55 if ni == 0 else 0.32
                left += v * env * g * (1 - pan)
                right += v * env * g * pan
    # slow filter-ish movement: amplitude LFO on upper partials approximated by tremolo
    lfo = 0.85 + 0.15 * np.sin(2 * np.pi * 0.07 * t)
    left = lp_fast(left * lfo, 900, 2)
    right = lp_fast(right * lfo, 900, 2)
    # sub pulse on chord roots, gentle heartbeat at 72 bpm from 18.5 s on
    sub = np.zeros_like(t)
    beat = 60 / 72
    for bt in np.arange(18.5, total - 4, beat):
        ci = min(int(bt / seg), len(chords) - 1)
        f = note(chords[ci][0] - 12)
        idx = (t >= bt) & (t < bt + 0.9)
        tt = t[idx] - bt
        sub[idx] += np.sin(2 * np.pi * f * tt) * np.exp(-tt * 5) * (1 - np.exp(-tt * 200))
    # airy noise layer
    air = lp_fast(hp_fast(r.standard_normal(len(t)), 2500), 7000) * 0.05
    mix_env = np.interp(t, [0, 4, 17, 18.6, 44, 47, 52, total], [0.0, 0.55, 0.7, 1.0, 1.0, 0.85, 0.7, 0.0])
    L = (left + sub * 0.9 + air) * mix_env
    R = (right + sub * 0.9 + air[::-1]) * mix_env
    return np.stack([L, R], axis=1)


# ---------------------------------------------------------------- one-shots
def make_riser(sec: float = 3.2) -> np.ndarray:
    t = t_axis(sec)
    p = t / sec
    noise = rng(11).standard_normal(len(t))
    cutoff = 300 + 7000 * p**2.2
    n = onepole_lp(noise, cutoff)
    n = onepole_lp(n, cutoff)
    f = 180 * (1 + 6 * p**2)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.35 + np.sin(2 * np.pi * np.cumsum(f * 1.5) / SR) * 0.15
    env = p**2.4
    x = (n * 0.9 + tone) * env
    x[-int(0.02 * SR) :] *= np.linspace(1, 0, int(0.02 * SR))
    return reverb(x, 1.2, 0.25, 12)


def make_impact(big: bool = False, seed: int = 21) -> np.ndarray:
    sec = 2.4 if big else 1.6
    t = t_axis(sec)
    f = 40 + (95 if big else 70) * np.exp(-t * 9)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * (2.2 if big else 3.5))
    click = lp_fast(rng(seed).standard_normal(len(t)), 2200 if big else 1400) * np.exp(-t * 28) * 0.6
    x = body + click
    x = x * (1 - np.exp(-t * 900))
    return reverb(x, 2.0 if big else 1.3, 0.3, seed + 1)


def make_whoosh(sec: float = 1.1, seed: int = 31) -> np.ndarray:
    t = t_axis(sec)
    p = t / sec
    noise = rng(seed).standard_normal(len(t))
    centre = 400 + 2400 * np.sin(np.pi * p)
    x = onepole_lp(noise, centre) - onepole_lp(noise, centre * 0.35)
    env = np.sin(np.pi * p) ** 2
    return x * env


def make_key(seed: int, pitch: float, heavy: bool = False) -> np.ndarray:
    t = t_axis(0.12 if not heavy else 0.2)
    r = rng(seed)
    tick = hp_fast(r.standard_normal(len(t)), 2500) * np.exp(-t * (420 if not heavy else 300))
    thock = np.sin(2 * np.pi * pitch * t) * np.exp(-t * (70 if not heavy else 45)) * (0.5 if not heavy else 0.8)
    clack = np.sin(2 * np.pi * pitch * 9.7 * t) * np.exp(-t * 260) * 0.25
    x = tick * 0.8 + thock + clack
    return x * (1 - np.exp(-t * 4000))


def make_mark() -> np.ndarray:
    t = t_axis(0.6)
    x = (np.sin(2 * np.pi * 1318.5 * t) + 0.4 * np.sin(2 * np.pi * 2637 * t)) * np.exp(-t * 9)
    return reverb(x * (1 - np.exp(-t * 2000)), 0.8, 0.25, 41)


def make_chime() -> np.ndarray:
    t = t_axis(4.5)
    x = np.zeros_like(t)
    for start, f0, g in ((0.0, note(81), 1.0), (0.14, note(88), 0.7), (0.30, note(93), 0.45)):
        tt = np.clip(t - start, 0, None)
        on = (t >= start).astype(float)
        for ratio, amp, dec in ((1.0, 1.0, 1.2), (2.0, 0.45, 2.0), (2.76, 0.3, 3.0), (5.4, 0.12, 5.0), (8.9, 0.05, 8.0)):
            x += on * g * amp * np.sin(2 * np.pi * f0 * ratio * tt) * np.exp(-tt * dec) * (1 - np.exp(-tt * 3000))
    return reverb(x, 2.5, 0.35, 51)


if __name__ == "__main__":
    bed = make_bed()
    m = np.max(np.abs(bed)) + 1e-9
    save("bed", bed / m)
    save("riser", make_riser(), stereo_width=0.6)
    save("impact", make_impact(False, 21), peak=0.8, stereo_width=0.3)
    save("hit", make_impact(True, 25), peak=0.89, stereo_width=0.5)
    save("whoosh", make_whoosh(1.1, 31), peak=0.6, stereo_width=0.7)
    save("whoosh2", make_whoosh(1.4, 33), peak=0.6, stereo_width=0.7)
    save("key1", make_key(61, 190), peak=0.5)
    save("key2", make_key(62, 210), peak=0.5)
    save("key3", make_key(63, 175), peak=0.5)
    save("enter", make_key(64, 140, heavy=True), peak=0.7)
    save("mark", make_mark(), peak=0.35, stereo_width=0.4)
    save("chime", make_chime(), peak=0.8, stereo_width=0.6)
