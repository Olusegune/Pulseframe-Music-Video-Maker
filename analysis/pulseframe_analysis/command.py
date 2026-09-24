"""Director Command (PRD §26): natural-language direction applied to the shot plan.

"Make the second chorus more energetic" -> the model picks the affected shots and rewrites their
direction fields. Story beats, order and timing never change. Every command is undoable: the prior
version of each changed shot is kept in commands.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid

from .director import DEFAULT_MODEL, _client, resolve_model

EDITABLE = ["visual_prompt", "purpose", "emotion", "performance_intensity", "performance", "expression", "movement",
            "framing", "lens", "camera_movement", "camera_energy", "lighting", "environment", "wardrobe", "continuity"]

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["summary", "changes", "not_done"],
    "properties": {
        "summary": {"type": "string", "description": "One sentence: what was changed, in director's language."},
        "not_done": {"type": "string", "description": "Anything asked that can't be done by re-directing shots (else empty)."},
        "changes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["shot_id", "edits"],
            "properties": {
                "shot_id": {"type": "string"},
                "edits": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["field", "value"],
                    "properties": {"field": {"type": "string", "enum": EDITABLE}, "value": {"type": "string"}}}},
            }}},
    },
}

SYSTEM = """You are the director of a music video, taking a note from the artist.
Apply the note by re-directing shots. Rules:
- Choose exactly the shots the note is about (use sections, times, shot ids, the current selection and playhead).
- Change only direction: acting, expression, movement, emotion and intensity (1-10), framing, lens, camera movement,
  camera energy (still|gentle|moderate|kinetic), lighting, setting, wardrobe, continuity, and the visual description.
- Never change story events, their order, who appears, or timing. Keep continuity with neighbouring shots.
- visual_prompt must stay a complete, concrete description of the frame, consistent with your other edits.
- Be proportionate: a small note means small edits. If part of the note can't be done this way (e.g. changing the
  song, or rendering), say so in not_done."""


def _read(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def _plan_path(d: str) -> str:
    """Commands edit the directed plan; a script/treatment-only project gets one seeded from its plan."""
    directed = os.path.join(d, "directed.json")
    if not os.path.exists(directed):
        prod = _read(os.path.join(d, "production.json"))
        if not prod:
            raise SystemExit("This project has no shots to direct yet.")
        _write(directed, prod)
    return directed


def run(d: str, instruction: str, selected: str | None, playhead: float | None) -> dict:
    path = _plan_path(d)
    plan = _read(path)
    sm = _read(os.path.join(d, "songmap.json"), {})
    shots = {s["id"]: s for sc in plan["scenes"] for s in sc["shots"]}
    index = [{"id": s["id"], "scene": s["scene"], "start": round(s["start"], 2), "end": round(s["end"], 2),
              "framing": s.get("framing"), "performers": s.get("performers", []),
              "what": (s.get("visual_prompt") or " ".join(s.get("beats", [])))[:220]} for s in shots.values()]
    sections, seen = [], {}
    for sec in sm.get("sections", []):  # "second chorus" needs numbered sections
        seen[sec["label"]] = seen.get(sec["label"], 0) + 1
        sections.append({"name": f"{sec['label'].title()} {seen[sec['label']]}", "start": sec["start"], "end": sec["end"]})
    brief = {"note": instruction, "selected_shot": selected, "playhead_seconds": playhead, "sections": sections,
             "characters": [{k: c.get(k) for k in ("name", "acting_notes")} for c in plan.get("characters", [])],
             "shots": index}
    client = _client()
    model = resolve_model(client, DEFAULT_MODEL)
    print(json.dumps({"event": "progress", "stage": "reading your note"}), flush=True)
    first = client.responses.create(
        model=model, input=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(brief, ensure_ascii=False)}],
        text={"format": {"type": "json_schema", "name": "scope", "strict": True, "schema": {
            "type": "object", "additionalProperties": False, "required": ["shot_ids"],
            "properties": {"shot_ids": {"type": "array", "items": {"type": "string"}}}}}},
    )
    scope = [i for i in json.loads(first.output_text)["shot_ids"] if i in shots][:30]
    if not scope:
        return {"summary": "No shots matched that note.", "not_done": instruction, "changed": [], "id": None}
    print(json.dumps({"event": "progress", "stage": f"re-directing {len(scope)} shot{'s' if len(scope) != 1 else ''}"}), flush=True)
    detail = {**brief, "shots": [{k: shots[i].get(k) for k in ["id", "start", "end", "beats", "performers", *EDITABLE]} for i in scope]}
    resp = client.responses.create(
        model=model, input=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(detail, ensure_ascii=False)}],
        text={"format": {"type": "json_schema", "name": "direction_change", "schema": SCHEMA, "strict": True}},
    )
    out = json.loads(resp.output_text)
    before, changed, now = {}, [], int(time.time())
    for ch in out["changes"]:
        s = shots.get(ch["shot_id"])
        if not s or ch["shot_id"] not in scope or not ch["edits"]:
            continue
        before[s["id"]] = {k: s.get(k) for k in EDITABLE + ["revised"]}
        for e in ch["edits"]:
            v = e["value"]
            if e["field"] == "performance_intensity":
                try:
                    v = max(1, min(10, int(float(v))))
                except ValueError:
                    continue
            s[e["field"]] = v
        s["revised"] = now
        changed.append(s["id"])
    if changed:
        _write(path, plan)
    hist = _read(os.path.join(d, "commands.json"), {"commands": []})
    entry = {"id": uuid.uuid4().hex[:10], "at": now, "note": instruction, "summary": out["summary"],
             "not_done": out["not_done"], "changed": changed, "before": before, "model": model}
    hist["commands"].append(entry)
    _write(os.path.join(d, "commands.json"), hist)
    return {k: entry[k] for k in ("id", "summary", "not_done", "changed")}


def undo(d: str, command_id: str) -> dict:
    path = _plan_path(d)
    plan = _read(path)
    hist = _read(os.path.join(d, "commands.json"), {"commands": []})
    entry = next((c for c in hist["commands"] if c["id"] == command_id and not c.get("undone")), None)
    if not entry:
        raise SystemExit("Nothing to undo.")
    for sc in plan["scenes"]:
        for s in sc["shots"]:
            prev = entry["before"].get(s["id"])
            if prev:
                for k, v in prev.items():
                    if v is None:
                        s.pop(k, None)
                    else:
                        s[k] = v
    _write(path, plan)
    entry["undone"] = int(time.time())
    _write(os.path.join(d, "commands.json"), hist)
    return {"id": command_id, "restored": list(entry["before"])}


def main(argv):
    p = argparse.ArgumentParser(prog="pulseframe-command")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("project"); r.add_argument("--note", required=True)
    r.add_argument("--selected"); r.add_argument("--playhead", type=float)
    u = sub.add_parser("undo"); u.add_argument("project"); u.add_argument("--id", required=True)
    a = p.parse_args(argv)
    try:
        data = run(a.project, a.note, a.selected, a.playhead) if a.cmd == "run" else undo(a.project, a.id)
        print(json.dumps({"event": "result", "data": data}, ensure_ascii=False), flush=True)
    except SystemExit as e:
        print(json.dumps({"event": "error", "message": str(e)}), flush=True)
        return 1
    except Exception as e:
        print(json.dumps({"event": "error", "message": f"{type(e).__name__}: {e}"}), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
