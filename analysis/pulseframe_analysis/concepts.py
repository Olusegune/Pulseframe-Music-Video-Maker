"""Song-first creative development (PRD §10–13) for projects without a script.

  directions  : Song Map + lyrics + references -> three distinct visual concepts (concepts.json)
  treatment   : chosen concept (+ notes) -> treatment, characters and scenes with shots, written as
                production.json in the same shape as a script import, so directing, rendering,
                review and export work unchanged.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from .director import DEFAULT_MODEL, _client, resolve_model
from .script_import import Character, Scene, _make_shot, consolidate, time_shots


def emit(**kw) -> None:
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def _read(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def _style_ids() -> list[str]:
    with open(os.path.join(os.path.dirname(__file__), "styles.json"), encoding="utf-8") as f:
        return [s["id"] for s in json.load(f)["styles"]]


def song_brief(d: str) -> dict:
    project = _read(os.path.join(d, "project.json"), {})
    sm = _read(os.path.join(d, "songmap.json"), {})
    lyrics = {}
    for l in sm.get("lyrics", []):
        lyrics.setdefault(l["section"], []).append(l["text"])
    return {
        "title": project.get("title"), "artist": project.get("artist"), "bpm": sm.get("bpm"),
        "duration_seconds": sm.get("duration"),
        "sections": [{"index": i, "label": s["label"], "tag": s.get("group"), "start": s["start"], "end": s["end"],
                      "energy_1_10": s["energy"], "mood": s["mood"]} for i, s in enumerate(sm.get("sections", []))],
        "lyrics_by_section": lyrics,
        "has_character_sheet": bool((project.get("references") or {}).get("characters")),
        "chosen_look": (project.get("look") or {}).get("style") if isinstance(project.get("look"), dict) else None,
    }


# ------------------------------------------------------------------ three directions

CONCEPT = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "premise", "mood", "performance_approach", "cinematic_style", "palette", "environment",
                 "wardrobe", "movement", "narrative_level", "hero_frame", "suggested_look"],
    "properties": {
        "title": {"type": "string", "description": "2–4 words, evocative."},
        "premise": {"type": "string", "description": "One sentence."},
        "mood": {"type": "string"},
        "performance_approach": {"type": "string", "description": "How the artist performs: acting, stillness, dance, instrument…"},
        "cinematic_style": {"type": "string"},
        "palette": {"type": "array", "items": {"type": "string"}, "description": "3–5 named colours."},
        "environment": {"type": "string"},
        "wardrobe": {"type": "string"},
        "movement": {"type": "string", "description": "Movement or dance approach; say so if there is little or none."},
        "narrative_level": {"type": "string", "enum": ["performance", "hybrid", "narrative"]},
        "hero_frame": {"type": "string", "description": "One striking image that sums up the video, described as a still."},
        "suggested_look": {"type": "string", "description": "An id from the look library."},
    },
}
DIRECTIONS = {"type": "object", "additionalProperties": False, "required": ["concepts"],
              "properties": {"concepts": {"type": "array", "items": CONCEPT}}}

SYSTEM_DIRECTIONS = """You are the creative director of PULSEFRAME, a music-video studio.
Listen to the song through its structure, energy curve and lyrics, then propose exactly three
music-video directions that are genuinely different from each other (e.g. one performance-led,
one hybrid, one narrative). Each must fit the song's emotional arc: quiet sections stay intimate,
peaks land on the choruses. Performance does not have to mean dancing. Be specific and visual;
avoid clichés and anything that needs text on screen. Respect the culture and language of the
lyrics. suggested_look must be one of the provided look ids."""


def directions(d: str, notes: str = "") -> dict:
    client = _client()
    model = resolve_model(client, DEFAULT_MODEL)
    brief = {**song_brief(d), "look_ids": _style_ids(), "artist_notes": notes}
    emit(event="progress", stage="imagining three directions")
    resp = client.responses.create(
        model=model,
        input=[{"role": "system", "content": SYSTEM_DIRECTIONS},
               {"role": "user", "content": json.dumps(brief, ensure_ascii=False)}],
        text={"format": {"type": "json_schema", "name": "directions", "schema": DIRECTIONS, "strict": True}},
    )
    out = json.loads(resp.output_text)
    ids = set(_style_ids())
    for c in out["concepts"]:
        if c["suggested_look"] not in ids:
            c["suggested_look"] = "auto"
    out["concepts"] = out["concepts"][:3]
    out["model"] = model
    _write(os.path.join(d, "concepts.json"), out)
    return out


# ------------------------------------------------------------------ treatment + shot plan

TREATMENT = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "logline", "visual_style", "characters", "scenes"],
    "properties": {
        "title": {"type": "string"},
        "logline": {"type": "string"},
        "visual_style": {"type": "string", "description": "Colour, light and symbolism, as in a treatment."},
        "characters": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "archetype", "appearance", "motivation", "acting_notes"],
            "properties": {"name": {"type": "string"}, "archetype": {"type": "string"}, "appearance": {"type": "string"},
                           "motivation": {"type": "string"}, "acting_notes": {"type": "string"}}}},
        "scenes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["first_section", "last_section", "heading", "setting", "atmosphere", "characters", "action",
                         "camera", "lighting", "performance", "vfx", "continuity", "shots"],
            "properties": {
                "first_section": {"type": "integer", "description": "Index of the first song section this scene covers."},
                "last_section": {"type": "integer", "description": "Index of the last song section this scene covers."},
                "heading": {"type": "string", "description": "Screenplay-style, e.g. 'EXT. ROOFTOP - SUNSET'."},
                "setting": {"type": "string"}, "atmosphere": {"type": "string"},
                "characters": {"type": "array", "items": {"type": "string"}},
                "action": {"type": "string"}, "camera": {"type": "string"}, "lighting": {"type": "string"},
                "performance": {"type": "string"}, "vfx": {"type": "string"}, "continuity": {"type": "string"},
                "shots": {"type": "array", "items": {"type": "string"},
                          "description": "Shot descriptions in order, each starting with framing, e.g. 'Close-up of …'."},
            }}},
    },
}

SYSTEM_TREATMENT = """You are the director writing the production treatment for a music video.
Develop the chosen concept into scenes that cover the whole song in order: every section index
belongs to exactly one scene, scenes are contiguous, and the first scene starts at section 0.
Give each scene roughly one shot per 2.5–3 seconds of music (fewer, longer shots in quiet parts;
more in peaks). Shots are visual and specific, start with their framing, and name who appears.
Characters: the artist is the lead; add others only if the concept needs them. Acting notes must be
concrete (how emotion shows in the body, eyes, breath) and suitable for actors. Keep the chosen look."""


def treatment(d: str, index: int, notes: str = "") -> dict:
    concepts = _read(os.path.join(d, "concepts.json"), {}) or {}
    try:
        concept = concepts["concepts"][index]
    except (KeyError, IndexError):
        raise SystemExit("Choose one of the three directions first.")
    client = _client()
    model = resolve_model(client, DEFAULT_MODEL)
    emit(event="progress", stage=f"writing the treatment for “{concept['title']}”")
    resp = client.responses.create(
        model=model,
        input=[{"role": "system", "content": SYSTEM_TREATMENT},
               {"role": "user", "content": json.dumps({"song": song_brief(d), "concept": concept, "notes": notes},
                                                       ensure_ascii=False)}],
        text={"format": {"type": "json_schema", "name": "treatment", "schema": TREATMENT, "strict": True}},
    )
    t = json.loads(resp.output_text)
    emit(event="progress", stage="planning shots on the beat")
    plan = build_plan(d, concept, t)
    _write(os.path.join(d, "production.json"), plan)
    _write(os.path.join(d, "treatment.json"), {"concept": concept, "treatment": t, "model": model, "notes": notes})
    return {"scenes": len(plan["scenes"]), "shots": sum(len(s["shots"]) for s in plan["scenes"]), "title": t["title"]}


def build_plan(d: str, concept: dict, t: dict) -> dict:
    """Treatment -> production plan in the script-import shape, timed to the Song Map."""
    sm = _read(os.path.join(d, "songmap.json"), {})
    sections = sm.get("sections", [])
    n = len(sections)
    chars = [Character(c["name"], c["archetype"], c["appearance"], c["motivation"], c["acting_notes"]) for c in t["characters"]]
    names = sorted((c.name for c in chars), key=len, reverse=True)
    scenes: list[Scene] = []
    covered = 0
    for i, raw in enumerate(sorted(t["scenes"], key=lambda s: s["first_section"])):
        first = max(covered, min(raw["first_section"], n - 1))
        last = max(first, min(raw["last_section"], n - 1))
        if i == len(t["scenes"]) - 1:
            last = n - 1  # the last scene always runs to the end of the song
        if first > last or first >= n:
            continue
        fields = {"LOGLINE": raw["action"], "SETTING": raw["setting"], "ATMOSPHERE": raw["atmosphere"],
                  "CHARACTER(S)": ", ".join(raw["characters"]), "ACTION": raw["action"],
                  "DIALOGUE": " ".join(l["text"] for l in sm.get("lyrics", [])
                                       if l.get("start") is not None and sections[first]["start"] <= l["start"] < sections[last]["end"])}
        notes = {"CAMERA": raw["camera"], "LIGHTING": raw["lighting"], "PERFORMANCE": raw["performance"],
                 "VFX/EFFECTS": raw["vfx"], "CONTINUITY": raw["continuity"]}
        sc = Scene(len(scenes) + 1, raw["heading"], fields, notes, [c for c in names if c in raw["characters"]])
        sc.start, sc.end = sections[first]["start"], sections[last]["end"]
        for k, desc in enumerate(raw["shots"], 1):
            sc.shots.append(_make_shot(sc, k, desc, names))
        if not sc.shots:
            sc.shots.append(_make_shot(sc, 1, raw["action"], names))
        scenes.append(sc)
        covered = last + 1
    if scenes:
        scenes[0].start = 0.0
        scenes[-1].end = sm.get("duration", scenes[-1].end)
        for a, b in zip(scenes, scenes[1:]):
            b.start = a.end
    for sc in scenes:
        consolidate(sc)
    time_shots(scenes, sm)
    meta = {"TITLE": t["title"], "LOGLINE": t["logline"], "VISUAL STYLE": t["visual_style"],
            "CONCEPT": concept["title"], "MOOD": concept["mood"]}
    return {"schema_version": 1, "source": "treatment", "meta": meta, "characters": [asdict(c) for c in chars],
            "scenes": [asdict(s) for s in scenes]}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="pulseframe-concepts")
    sub = p.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("directions"); a1.add_argument("project"); a1.add_argument("--notes", default="")
    a2 = sub.add_parser("treatment"); a2.add_argument("project"); a2.add_argument("--index", type=int, required=True)
    a2.add_argument("--notes", default="")
    a = p.parse_args(argv)
    try:
        data = directions(a.project, a.notes) if a.cmd == "directions" else treatment(a.project, a.index, a.notes)
        emit(event="result", data=data)
    except SystemExit as e:
        emit(event="error", message=str(e))
        return 1
    except Exception as e:
        emit(event="error", message=f"{type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
