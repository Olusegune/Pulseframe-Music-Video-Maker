"""Song analysis -> SongMap.

M0 baseline built on librosa. Heavier models (Beat This! downbeats, structure
models, Demucs vocals, WhisperX lyrics) slot in behind the same SongMap output.
Progress is emitted as JSON lines on stdout so the UI can drive the reveal
animation; the final SongMap is written to --out.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field

import librosa
import numpy as np

SR = 22050
HOP = 512
BEAT_HOP = 128
SCHEMA_VERSION = 1


@dataclass
class Section:
    start: float
    end: float
    label: str          # INTRO / VERSE / PRE-CHORUS / CHORUS / BRIDGE / OUTRO
    group: str          # repetition group (A, B, C...) — same letter = same material
    energy: int         # 1..10
    mood: str


@dataclass
class SongMap:
    schema_version: int
    duration: float
    bpm: float
    beats: list[float]
    downbeats: list[float]
    energy_curve: list[list[float]]          # [time, 0..1]
    accents: list[float]
    sections: list[Section] = field(default_factory=list)
    lyrics: list[dict] = field(default_factory=list)     # [{section, text, start, end}]
    lyric_match: float | None = None                     # fraction of lyric words heard
    peaks: list[float] = field(default_factory=list)     # 2000-point waveform envelope for display
    analyzer: str = "librosa-baseline"


def emit(stage: str, progress: float, **data) -> None:
    print(json.dumps({"event": "progress", "stage": stage, "progress": round(progress, 3), **data}), flush=True)


def _downbeats(beats: np.ndarray, onset_env: np.ndarray, beat_frames: np.ndarray, meter: int = 4) -> np.ndarray:
    """Pick the bar phase whose beats carry the most onset strength (crude, 4/4 assumption)."""
    if len(beats) < meter:
        return beats
    strength = onset_env[np.clip(beat_frames, 0, len(onset_env) - 1)]
    scores = [strength[p::meter].mean() for p in range(meter)]
    return beats[int(np.argmax(scores))::meter]


def _fit_grid(raw: np.ndarray, duration: float) -> tuple[np.ndarray, float]:
    """Least-squares fit of a constant-tempo grid to tracked beats, extended over the whole song.

    Baseline assumes steady tempo; tempo-change handling arrives with the model-based tracker.
    """
    if len(raw) < 8:
        return raw, 0.0
    period = float(np.median(np.diff(raw)))
    idx = np.round((raw - raw[0]) / period)
    period, offset = np.polyfit(idx, raw, 1)
    start = offset - np.floor(offset / period) * period
    grid = np.arange(start, duration, period)
    return grid, 60.0 / period


def _novelty_boundaries(feats: np.ndarray, kernel: int = 16) -> np.ndarray:
    """Foote checkerboard novelty over a beat-level self-similarity matrix."""
    # z-score each feature row so one dominant contrast (e.g. silent intro) can't mask the rest
    f = (feats - feats.mean(axis=1, keepdims=True)) / (feats.std(axis=1, keepdims=True) + 1e-9)
    f = f / (np.linalg.norm(f, axis=0, keepdims=True) + 1e-9)
    ssm = f.T @ f
    n = ssm.shape[0]
    half = kernel // 2
    g = np.outer(np.hanning(kernel), np.hanning(kernel))
    sign = np.ones((kernel, kernel))
    sign[:half, half:] = sign[half:, :half] = -1
    k = g * sign
    padded = np.pad(ssm, half, mode="edge")
    nov = np.array([(padded[i:i + kernel, i:i + kernel] * k).sum() for i in range(n)])
    nov = np.maximum(nov, 0)
    nov /= nov.max() or 1.0
    peaks = librosa.util.peak_pick(nov, pre_max=8, post_max=8, pre_avg=8, post_avg=8, delta=0.1, wait=16)
    return peaks[nov[peaks] > 0.1]


def _snap(t: float, grid: np.ndarray) -> float:
    return float(grid[np.argmin(np.abs(grid - t))]) if len(grid) else t


MOODS = [(3, "Dreamlike"), (5, "Intimate"), (7, "Building"), (9, "Driving"), (11, "Celebratory")]


def _mood(energy: int) -> str:
    return next(m for limit, m in MOODS if energy < limit)


def _label_sections(groups: list[str], energies: list[int], durations: list[float]) -> list[str]:
    n = len(groups)
    counts = {g: groups.count(g) for g in set(groups)}
    mean_energy = {g: np.mean([e for gg, e in zip(groups, energies) if gg == g]) for g in counts}
    repeated = [g for g in counts if counts[g] > 1]
    chorus = max(repeated or counts, key=lambda g: mean_energy[g])
    labels = []
    for i, (g, e) in enumerate(zip(groups, energies)):
        if g == chorus:
            labels.append("CHORUS")
        elif i == 0 and e <= 4:
            labels.append("INTRO")
        elif i == n - 1 and e <= 5:
            labels.append("OUTRO")
        elif (i + 1 < n and groups[i + 1] == chorus and e < mean_energy[chorus]
              and durations[i] < 0.75 * np.mean([d for gg, d in zip(groups, durations) if gg == chorus])):
            labels.append("PRE-CHORUS")
        elif counts[g] == 1 and i > n / 2:
            labels.append("BRIDGE")
        else:
            labels.append("VERSE")
    return labels


def analyze(path: str) -> SongMap:
    emit("loading", 0.0)
    y, sr = librosa.load(path, sr=SR, mono=True)
    duration = float(len(y) / sr)
    wave_peaks = (np.abs(y[: len(y) // 2000 * 2000]).reshape(2000, -1).max(axis=1).round(3).tolist()
             if len(y) >= 2000 else [])
    emit("waveform", 0.1, duration=duration, peaks=wave_peaks)

    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    # Fine hop for beat timing: at HOP=512 tempo is quantized (~120 BPM reads as 117.45).
    fine_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=BEAT_HOP)
    _, raw_frames = librosa.beat.beat_track(onset_envelope=fine_env, sr=sr, hop_length=BEAT_HOP, trim=False)
    raw = librosa.frames_to_time(raw_frames, sr=sr, hop_length=BEAT_HOP)
    beats, bpm = _fit_grid(raw, duration)
    beat_frames = librosa.time_to_frames(beats, sr=sr, hop_length=HOP)
    downbeats = _downbeats(beats, onset_env, beat_frames)
    emit("beats", 0.35, bpm=round(bpm, 2), beats=beats.round(3).tolist())

    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    rms_t = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=HOP)
    win = max(1, int(sr / HOP))  # ~1s smoothing
    smooth = np.convolve(rms, np.ones(win) / win, mode="same")
    norm = (smooth - smooth.min()) / (np.ptp(smooth) or 1.0)
    step = max(1, int(0.5 * sr / HOP))
    energy_curve = [[round(float(t), 2), round(float(e), 3)] for t, e in zip(rms_t[::step], norm[::step])]
    emit("energy", 0.5, energy_curve=energy_curve)

    peaks = librosa.util.peak_pick(onset_env, pre_max=10, post_max=10, pre_avg=20, post_avg=20, delta=0.5, wait=20)
    peak_strength = onset_env[peaks]
    top = peaks[np.argsort(peak_strength)[::-1][: max(8, int(duration / 6))]]
    accents = sorted(round(float(t), 3) for t in librosa.frames_to_time(top, sr=sr, hop_length=HOP))
    emit("accents", 0.6, accents=accents)

    # Structure: beat-synchronous timbre + harmony + loudness, novelty-based segmentation.
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, hop_length=HOP, n_mfcc=13)
    loud = librosa.util.sync(rms[np.newaxis, :], beat_frames, aggregate=np.mean)
    loud = (loud - loud.mean()) / (loud.std() or 1.0)
    feats = librosa.util.sync(np.vstack([librosa.util.normalize(chroma), librosa.util.normalize(mfcc)]),
                              beat_frames, aggregate=np.median)
    feats = np.vstack([feats, np.repeat(loud, 4, axis=0)])  # loudness weighted so energy shifts count
    bounds_beats = _novelty_boundaries(feats)
    beat_times = np.concatenate([[0.0], beats])  # sync() column i starts at beat i-1
    grid = downbeats if len(downbeats) else beats
    edges = sorted({0.0, duration, *(_snap(float(beat_times[min(b, len(beat_times) - 1)]), grid)
                                      for b in bounds_beats)})
    edges = [e for i, e in enumerate(edges) if i == 0 or e - edges[i - 1] > 4.0 or e == duration]

    # Group repeated material by cosine similarity of section-mean features.
    seg_feats, energies = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        mask = (beats >= a) & (beats < b)
        cols = feats[:, 1:][:, mask[: feats.shape[1] - 1]] if mask.any() else feats[:, :1]
        v = cols.mean(axis=1)
        seg_feats.append(v / (np.linalg.norm(v) or 1.0))
        emask = (rms_t >= a) & (rms_t < b)
        energies.append(int(np.clip(round(1 + 9 * float(norm[emask].mean() if emask.any() else 0)), 1, 10)))
    groups: list[str] = []
    reps: list[np.ndarray] = []
    for v in seg_feats:
        sims = [float(v @ r) for r in reps]
        if sims and max(sims) > 0.97:
            groups.append(chr(65 + int(np.argmax(sims))))
        else:
            reps.append(v)
            groups.append(chr(65 + len(reps) - 1))
    labels = _label_sections(groups, energies, [b - a for a, b in zip(edges[:-1], edges[1:])])
    sections = [Section(round(a, 2), round(b, 2), lab, g, e, _mood(e))
                for (a, b), lab, g, e in zip(zip(edges[:-1], edges[1:]), labels, groups, energies)]
    emit("sections", 0.9, sections=[asdict(s) for s in sections])

    song_map = SongMap(SCHEMA_VERSION, round(duration, 3), round(bpm, 2), beats.round(3).tolist(),
                       downbeats.round(3).tolist(), energy_curve, accents, sections)
    song_map.peaks = wave_peaks
    return song_map


def _apply_lyrics(sm: SongMap, audio: str, lyrics_path: str, work_dir: str) -> None:
    """Replace novelty sections with lyric-bounded ones and attach timed lines."""
    from . import lyrics as L
    with open(lyrics_path, encoding="utf-8") as f:
        secs = L.parse_lyrics(f.read())
    emit("vocals", 0.92)
    vocals = L.separate_vocals(audio, work_dir)
    emit("lyrics", 0.95)
    words = L.transcribe_words(vocals, prompt=" ".join(ln.text for s in secs for ln in s.lines))
    sm.lyric_match = round(L.align(secs, words), 3)
    curve = np.array(sm.energy_curve)
    out = []
    for i, sec in enumerate(L.sections_from_lyrics(secs, sm.duration, sm.downbeats)):
        m = (curve[:, 0] >= sec["start"]) & (curve[:, 0] < sec["end"])
        e = int(np.clip(round(1 + 9 * float(curve[m, 1].mean() if m.any() else 0)), 1, 10))
        out.append(Section(round(sec["start"], 2), round(sec["end"], 2), sec["label"], sec["tag"], e, _mood(e)))
    sm.sections = out
    sm.lyrics = [{"section": s.tag, "text": ln.text,
                  "start": None if ln.start is None else round(ln.start, 2),
                  "end": None if ln.end is None else round(ln.end, 2)} for s in secs for ln in s.lines]
    sm.analyzer = "librosa-baseline+demucs+whisper-align"
    emit("sections", 0.99, sections=[asdict(x) for x in out], lyrics=sm.lyrics)


def main(argv: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="pulseframe-analysis")
    p.add_argument("audio")
    p.add_argument("--out", required=True)
    p.add_argument("--lyrics", help="lyrics text with [Section] tags; enables lyric-bounded sections")
    p.add_argument("--work-dir", help="cache for stems (default: next to --out)")
    a = p.parse_args(argv)
    try:
        sm = analyze(a.audio)
        if a.lyrics:
            import os
            _apply_lyrics(sm, a.audio, a.lyrics, a.work_dir or os.path.join(os.path.dirname(os.path.abspath(a.out)), "stems"))
    except Exception as e:  # surfaced to the app as a structured error
        print(json.dumps({"event": "error", "message": str(e)}), flush=True)
        return 1
    emit("done", 1.0)
    import os
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(asdict(sm), f, indent=1)
    os.replace(tmp, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
