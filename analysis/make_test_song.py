"""Synthesize a known-structure test song (120 BPM, 4/4) so analysis can be checked
against ground truth without copyrighted audio.

Structure (bars of 2 s): INTRO 8 | VERSE 8 | CHORUS 8 | VERSE 8 | CHORUS 8 | OUTRO 4
"""
import sys

import numpy as np
import soundfile as sf

SR = 22050
BPM = 120
BEAT = 60 / BPM


def tone(freqs, dur, amp):
    t = np.arange(int(dur * SR)) / SR
    return amp * sum(np.sin(2 * np.pi * f * t) for f in freqs) / len(freqs)


def kick(amp):
    t = np.arange(int(0.25 * SR)) / SR
    return amp * np.sin(2 * np.pi * (50 + 100 * np.exp(-t * 30)) * t) * np.exp(-t * 12)


def hat(amp):
    n = int(0.05 * SR)
    return amp * np.random.default_rng(0).standard_normal(n) * np.exp(-np.arange(n) / SR * 80)


SECTIONS = [  # name, bars, chord freqs, pad amp, drums on, hats on
    ("INTRO", 8, [220, 277, 330], 0.10, False, False),
    ("VERSE", 8, [196, 247, 294], 0.15, True, False),
    ("CHORUS", 8, [262, 330, 392, 523], 0.30, True, True),
    ("VERSE", 8, [196, 247, 294], 0.15, True, False),
    ("CHORUS", 8, [262, 330, 392, 523], 0.30, True, True),
    ("OUTRO", 4, [220, 277, 330], 0.08, False, False),
]


def main(out):
    parts, t0, truth = [], 0.0, []
    for name, bars, chord, pad, drums, hats in SECTIONS:
        dur = bars * 4 * BEAT
        seg = tone(chord, dur, pad)
        if drums:
            for b in range(bars * 4):
                i = int(b * BEAT * SR)
                k = kick(0.8 if b % 4 == 0 else 0.5)
                seg[i:i + len(k)] += k[: len(seg) - i]
        if hats:
            for b in range(bars * 8):
                i = int(b * BEAT / 2 * SR)
                h = hat(0.15)
                seg[i:i + len(h)] += h[: len(seg) - i]
        parts.append(seg)
        truth.append((name, round(t0, 2), round(t0 + dur, 2)))
        t0 += dur
    y = np.concatenate(parts)
    sf.write(out, y / np.abs(y).max() * 0.9, SR)
    for row in truth:
        print(*row)


if __name__ == "__main__":
    main(sys.argv[1])
