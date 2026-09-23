"""Lyric alignment: known lyrics + word-timestamped transcription -> timed lines and sections.

Transcription is only a timing source. The user's lyrics stay authoritative, so
pidgin, slang and mishearings don't corrupt the text — we align the two word
sequences and read timestamps off the matches.
"""
from __future__ import annotations

import difflib
import os
import re
import sys
from dataclasses import dataclass

TAG = re.compile(r"^\[(.+?)\]\s*$")


@dataclass
class LyricLine:
    section_index: int
    text: str
    start: float | None = None
    end: float | None = None


@dataclass
class LyricSection:
    tag: str        # as written, e.g. "Verse 1"
    label: str      # normalized: VERSE / PRE-CHORUS / CHORUS / BRIDGE / ...
    lines: list[LyricLine]


def _norm_label(tag: str) -> str:
    t = tag.lower()
    for key, label in (("pre", "PRE-CHORUS"), ("chorus", "CHORUS"), ("hook", "CHORUS"), ("verse", "VERSE"),
                       ("bridge", "BRIDGE"), ("intro", "INTRO"), ("outro", "OUTRO")):
        if key in t:
            return label
    return tag.upper()


def parse_lyrics(text: str) -> list[LyricSection]:
    sections: list[LyricSection] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = TAG.match(line)
        if m:
            sections.append(LyricSection(m.group(1), _norm_label(m.group(1)), []))
            continue
        if not sections:
            sections.append(LyricSection("Verse", "VERSE", []))
        sections[-1].lines.append(LyricLine(len(sections) - 1, line))
    return sections


def _tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", s.lower().replace("’", "'"))


def _enable_cuda_dlls() -> None:
    """pip-installed NVIDIA wheels ship DLLs that Windows won't find on its own."""
    if sys.platform != "win32":
        return
    try:
        import nvidia  # type: ignore
    except ImportError:
        return
    for base in nvidia.__path__:
        for sub in os.listdir(base):
            d = os.path.join(base, sub, "bin")
            if os.path.isdir(d):
                os.add_dll_directory(d)
                os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]


def transcribe_words(audio: str, prompt: str = "", model_size: str = "large-v3") -> list[tuple[str, float, float]]:
    _enable_cuda_dlls()
    from faster_whisper import WhisperModel
    try:
        model = WhisperModel(model_size, device="cuda", compute_type="float16")
    except Exception:
        model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(audio, word_timestamps=True, vad_filter=True,
                                   initial_prompt=prompt[:800] or None, condition_on_previous_text=False)
    return [(w.word, w.start, w.end) for seg in segments for w in seg.words]


def align(sections: list[LyricSection], words: list[tuple[str, float, float]]) -> float:
    """Fill line start/end in place. Returns fraction of lyric words matched."""
    lyric_tokens: list[tuple[str, LyricLine]] = [(t, ln) for s in sections for ln in s.lines for t in _tokens(ln.text)]
    heard: list[tuple[str, float, float]] = [(t, a, b) for w, a, b in words for t in _tokens(w)]
    sm = difflib.SequenceMatcher(a=[t for t, _ in lyric_tokens], b=[t for t, _, _ in heard], autojunk=False)
    matched = 0
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            _, line = lyric_tokens[blk.a + k]
            _, a, b = heard[blk.b + k]
            line.start = a if line.start is None else min(line.start, a)
            line.end = b if line.end is None else max(line.end, b)
            matched += 1
    # Interpolate lines that received no matches between their timed neighbours.
    lines = [ln for s in sections for ln in s.lines]
    for i, ln in enumerate(lines):
        if ln.start is None:
            prev = next((lines[j].end for j in range(i - 1, -1, -1) if lines[j].end is not None), None)
            nxt = next((lines[j].start for j in range(i + 1, len(lines)) if lines[j].start is not None), None)
            if prev is not None and nxt is not None:
                ln.start, ln.end = prev, nxt
    return matched / max(1, len(lyric_tokens))
