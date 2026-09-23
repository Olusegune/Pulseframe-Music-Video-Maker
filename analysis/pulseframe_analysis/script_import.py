"""Screenplay-style script (PDF/text) + SongMap -> Scenes and Shot Contracts.

Deterministic first pass: the writer's scenes, shots and production notes are
preserved verbatim; PULSEFRAME only decides *when* each shot happens by
anchoring scenes to the timed lyric lines they sing and cutting on beats.
Director-Engine enrichment (OpenAI) layers on top of these contracts later.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field

FIELDS = ["LOGLINE", "SETTING", "ATMOSPHERE", "CHARACTER(S)", "ACTION", "DIALOGUE", "PRODUCTION NOTES", "SHOTS"]
NOTE_KEYS = ["CAMERA", "LIGHTING", "PERFORMANCE", "AUDIO", "VFX/EFFECTS", "CONTINUITY"]
SHOT_TYPES = [  # (pattern, framing, duration weight)
    (r"extreme close-up|macro", "extreme close-up", 0.8),
    (r"close-up|tight", "close-up", 0.9),
    (r"medium", "medium", 1.0),
    (r"point[- ]of[- ]view|pov", "point of view", 1.0),
    (r"over .*shoulder|over-the-shoulder", "over the shoulder", 1.0),
    (r"two-shot", "two-shot", 1.1),
    (r"wide|establishing|aerial|silhouette|overhead", "wide", 1.3),
    (r"montage|series of", "montage", 1.3),
]
MOVES = [r"tracking", r"push", r"pullback|pull back", r"dolly", r"handheld", r"steadicam", r"circl", r"crane|aerial",
         r"static", r"match cut", r"long-lens"]


@dataclass
class Character:
    name: str
    archetype: str = ""
    appearance: str = ""
    motivation: str = ""
    acting_notes: str = ""


@dataclass
class Shot:
    id: str
    scene: int
    number: int
    description: str
    framing: str
    camera_moves: list[str]
    performers: list[str]
    start: float = 0.0
    end: float = 0.0
    section: str = ""
    lyrics: list[str] = field(default_factory=list)
    sync_accents: list[float] = field(default_factory=list)
    source_shots: list[str] = field(default_factory=list)  # script shot ids this contract covers
    beats: list[str] = field(default_factory=list)          # ordered story beats (merged shots)
    renderer: str = "auto"
    state: str = "planned"
    flags: list[str] = field(default_factory=list)


@dataclass
class Scene:
    number: int
    heading: str
    fields: dict[str, str]
    notes: dict[str, str]
    characters: list[str]
    sung_lines: list[int] = field(default_factory=list)   # indexes into SongMap.lyrics
    start: float = 0.0
    end: float = 0.0
    shots: list[Shot] = field(default_factory=list)


def read_text(path: str) -> str:
    if path.lower().endswith(".pdf"):
        from pypdf import PdfReader
        text = "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
    else:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    return re.sub(r"\s+", " ", text.replace("’", "'")).strip()


def _split_fields(body: str, keys: list[str]) -> dict[str, str]:
    pat = "|".join(re.escape(k) for k in keys)
    parts = re.split(rf"(?:●\s*)?\b({pat}):", body)
    out: dict[str, str] = {}
    for k, v in zip(parts[1::2], parts[2::2]):
        out.setdefault(k, v.strip(" ●"))
    return out


def parse_script(text: str) -> tuple[dict[str, str], list[Character], list[Scene]]:
    heading_re = re.compile(r"((?:INT\.|EXT\.)[^:]*?-\s*[A-Z][A-Z ]+?)(?=\s+LOGLINE:)")
    heads = list(heading_re.finditer(text))
    preamble = text[: heads[0].start()] if heads else text

    char_chunks = re.split(r"\bCHARACTER:\s*", preamble)
    meta = _split_fields(char_chunks[0], ["TITLE", "LOGLINE", "GENRE", "THEMES", "TONE", "TARGET AUDIENCE",
                                          "DURATION", "SETTING", "VISUAL STYLE"])
    characters = []
    for chunk in char_chunks[1:]:
        m = re.match(r"([A-Z][A-Z ]+?)\s+ARCHETYPE:", chunk)
        if not m:
            continue
        f = _split_fields(chunk, ["ARCHETYPE", "APPEARANCE", "MOTIVATION", "ACTING NOTES"])
        characters.append(Character(m.group(1).title(), f.get("ARCHETYPE", ""), f.get("APPEARANCE", ""),
                                    f.get("MOTIVATION", ""), f.get("ACTING NOTES", "")))

    names = sorted((c.name for c in characters), key=len, reverse=True)
    scenes = []
    for i, h in enumerate(heads):
        body = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        f = _split_fields(body, FIELDS)
        notes = _split_fields(f.get("PRODUCTION NOTES", ""), NOTE_KEYS)
        cast = [n for n in names if n.lower() in f.get("CHARACTER(S)", "").lower()]
        scene = Scene(i + 1, h.group(1).strip(), f, notes, cast)
        shot_text = re.sub(r"\bEND CARD:.*$", "", f.get("SHOTS", ""))
        for n, desc in re.findall(r"SHOT (\d+):\s*(.*?)(?=\s*●?\s*SHOT \d+:|$)", shot_text):
            scene.shots.append(_make_shot(scene, int(n), desc.strip(" ●"), names))
        scenes.append(scene)
    end_card = re.search(r"END CARD:\s*(.*?)(?:FADE OUT\.|$)", text)
    if end_card:
        meta["END CARD"] = end_card.group(1).strip()
    return meta, characters, scenes


def _make_shot(scene: Scene, n: int, desc: str, names: list[str]) -> Shot:
    low = desc.lower()
    framing, _ = next(((fr, w) for p, fr, w in SHOT_TYPES if re.search(p, low)), ("medium", 1.0))
    moves = [m.split("|")[0] for m in MOVES if re.search(m, low)]
    performers = []
    for name in names:  # "Young Sege" must not also count as "Sege"
        if name.lower() in low.replace("young sege", "" if name == "Sege" else "young sege"):
            performers.append(name)
    if not performers and re.search(r"\b(his|he|him)\b", low) and "Sege" in scene.characters:
        performers = ["Sege"]
    sid = f"S{scene.number:02d}-{n:02d}"
    return Shot(sid, scene.number, n, desc, framing, moves, performers, source_shots=[sid], beats=[desc])


FRAMING_ORDER = ["extreme close-up", "close-up", "point of view", "over the shoulder", "medium", "two-shot",
                 "montage", "wide"]
MIN_SHOT = 2.0        # seconds; below this a generated shot doesn't read
LONG_TAKE_MIN = 2.5   # scenes whose camera notes ask for long takes / minimal movement
MAX_BEATS = 3         # more story beats than this can't be carried by one generated shot


def consolidate(scene: Scene) -> None:
    """Merge adjacent shots until the scene's average shot meets the minimum readable length.

    Prefers pairs that share performers (one continuous move can cover both beats) and keeps
    every original description as an ordered beat, so no story information is lost.
    """
    cam = scene.notes.get("CAMERA", "").lower()
    floor = LONG_TAKE_MIN if re.search(r"long(er)? takes|minimal movement", cam) else MIN_SHOT
    span = scene.end - scene.start
    target = max(1, min(len(scene.shots), int(span // floor)))

    def affinity(a: Shot, b: Shot) -> float:
        shared = len(set(a.performers) & set(b.performers))
        return shared + (0.5 if a.framing == b.framing else 0) - 0.1 * (len(a.beats) + len(b.beats))

    while len(scene.shots) > target:
        pairs = [k for k in range(len(scene.shots) - 1)
                 if len(scene.shots[k].beats) + len(scene.shots[k + 1].beats) <= MAX_BEATS]
        if not pairs:
            break
        i = max(pairs, key=lambda k: affinity(scene.shots[k], scene.shots[k + 1]))
        a, b = scene.shots[i], scene.shots[i + 1]
        wider = max(a.framing, b.framing, key=FRAMING_ORDER.index)
        moves = list(dict.fromkeys(a.camera_moves + b.camera_moves))
        if a.framing != b.framing:
            moves.append(f"continuous move {a.framing} -> {b.framing}")
        scene.shots[i:i + 2] = [Shot(a.id, scene.number, a.number, " Then: ".join([a.description, b.description]),
                                     wider, moves, list(dict.fromkeys(a.performers + b.performers)),
                                     source_shots=a.source_shots + b.source_shots, beats=a.beats + b.beats)]
    for k, sh in enumerate(scene.shots, 1):
        sh.number, sh.id = k, f"S{scene.number:02d}-{k:02d}"


def _norm(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", s.lower()))


def anchor_scenes(scenes: list[Scene], song_map: dict) -> None:
    """Claim timed lyric lines for each scene in order, then set scene spans."""
    lines = song_map.get("lyrics", [])
    ptr = 0
    for sc in scenes:
        dialog = _norm(sc.fields.get("DIALOGUE", ""))
        while ptr < len(lines) and _norm(lines[ptr]["text"]) in dialog:
            sc.sung_lines.append(ptr)
            ptr += 1
    downbeats = song_map["downbeats"]

    def bar_start(t: float) -> float:
        prior = [d for d in downbeats if d <= t + 0.15]
        return prior[-1] if prior else 0.0

    firsts = [lines[sc.sung_lines[0]]["start"] if sc.sung_lines else None for sc in scenes]
    for i, sc in enumerate(scenes):
        sc.start = 0.0 if i == 0 else scenes[i - 1].end
        nxt = next((t for t in firsts[i + 1:] if t is not None), None)
        sc.end = bar_start(nxt) if nxt is not None else song_map["duration"]
        if sc.end <= sc.start:
            sc.end = sc.start + 2.0


def time_shots(scenes: list[Scene], song_map: dict) -> None:
    """Split each scene across its shots by framing weight, cutting on the beat grid."""
    beats = song_map["beats"]
    lines = song_map.get("lyrics", [])
    sections = song_map["sections"]
    for sc in scenes:
        if not sc.shots:
            continue
        weights = [next((w for p, fr, w in SHOT_TYPES if fr == s.framing), 1.0) for s in sc.shots]
        total, span, t = sum(weights), sc.end - sc.start, sc.start
        cuts = [sc.start]
        for w in weights[:-1]:
            t += span * w / total
            cuts.append(min((b for b in beats if cuts[-1] < b < sc.end), key=lambda b: abs(b - t), default=t))
        cuts.append(sc.end)
        for shot, a, b in zip(sc.shots, cuts[:-1], cuts[1:]):
            shot.start, shot.end = round(a, 3), round(b, 3)
            mid = (a + b) / 2
            shot.section = next((s["section"] if "section" in s else s["group"] for s in sections
                                 if s["start"] <= mid < s["end"]), "")
            shot.lyrics = [ln["text"] for ln in lines if ln["start"] is not None
                           and ln["start"] < b and ln["end"] > a]
            shot.sync_accents = [x for x in song_map.get("accents", []) if a <= x < b]
            if (b - a) / len(shot.beats) < 1.0 - 0.05:
                shot.flags.append("overloaded: under 1s per story beat")
            if b - a < MIN_SHOT - 0.05:
                shot.flags.append("short: under 2s")


def build(script_path: str, song_map_path: str) -> dict:
    with open(song_map_path, encoding="utf-8") as f:
        song_map = json.load(f)
    meta, characters, scenes = parse_script(read_text(script_path))
    anchor_scenes(scenes, song_map)
    for sc in scenes:
        consolidate(sc)
    time_shots(scenes, song_map)
    return {"schema_version": 1, "meta": meta, "characters": [asdict(c) for c in characters],
            "scenes": [asdict(s) for s in scenes]}


if __name__ == "__main__":
    out = build(sys.argv[1], sys.argv[2])
    with open(sys.argv[3], "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
