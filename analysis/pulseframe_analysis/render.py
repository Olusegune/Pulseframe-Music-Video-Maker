"""Rendering: model capability manifests, Shot Contract -> provider request, persistent jobs.

Providers are adapters behind one internal request (PRD §15). Every model is described by a
manifest built from the provider's own published schema (fal OpenAPI / Kie OpenAPI), so Director
Mode can expose *every* input of any model without hand-written UI.

Jobs live in <project>/jobs.json and are written *before* any billable call (PRD §29):
  queued -> submitting -> submitted -> ready | failed
A job found in `submitting` after a crash is marked `uncertain` and never re-submitted
automatically; the user decides. Keys arrive via env (FAL_KEY, KIE_KEY) from the OS keychain.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import mimetypes
import os
import re
import sys
import time
import uuid

import requests

UA = {"User-Agent": "PULSEFRAME/0.1"}
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".pulseframe", "manifests")
ACTIVE = ("queued", "submitting", "submitted")

# Auto routing (Simple Mode): reference-to-video models keep characters consistent.
AUTO = {
    "fal": "bytedance/seedance-2.0/reference-to-video",
    "kie": "bytedance/seedance-2",
    "google": "veo-3.1-fast-generate-preview",
}
# Lip-sync pass: re-sync a finished take's mouth to the isolated vocal under the shot.
AUTO_LIPSYNC = {"fal": "fal-ai/sync-lipsync/v3", "kie": "volcengine/video-to-video-lip-sync"}
# Keyframes: a still for each shot, made with reference images, then animated (better consistency, cheaper retries).
AUTO_IMAGE = {
    "fal": "fal-ai/nano-banana/edit",
    "kie": "google/nano-banana-edit",
    "google": "gemini-3.1-flash-image",
}


def emit(**kw) -> None:
    print(json.dumps(kw, ensure_ascii=False), flush=True)


# ---------------------------------------------------------------- manifests

ROLE_NAMES = {
    "prompt": ["prompt"],
    "negative_prompt": ["negative_prompt"],
    "ref_images": ["image_urls", "reference_image_urls", "reference_images", "reference_image", "ref_image_urls",
                   "input_image_urls", "input_urls"],
    "ref_videos": ["video_urls", "reference_video_urls", "reference_videos"],
    "ref_audio": ["audio_urls", "reference_audio_urls"],
    "first_frame": ["image_url", "first_frame_url", "start_image_url", "first_frame_image", "input_image"],
    "last_frame": ["end_image_url", "last_frame_url", "tail_image_url", "last_frame_image"],
    "duration": ["duration", "duration_seconds", "seconds"],
    "aspect_ratio": ["aspect_ratio"],
    "resolution": ["resolution"],
    "audio": ["generate_audio", "with_audio", "enable_audio", "sound"],
    "seed": ["seed"],
    # lip-sync passes: the take to re-sync and the vocal that drives it
    "src_video": ["video_url", "input_video", "video"],
    "src_audio": ["audio_url", "input_audio", "audio"],
}


def _resolve(spec: dict, node: dict) -> dict:
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"].split("/")[-1]
        node = spec["components"]["schemas"][ref]
    if isinstance(node, dict) and "allOf" in node and len(node["allOf"]) == 1:
        return _resolve(spec, node["allOf"][0])
    return node


def _field(spec: dict, name: str, raw: dict, required: set) -> dict:
    raw = _resolve(spec, raw)
    types = [raw.get("type")] if raw.get("type") else [_resolve(spec, x).get("type") for x in raw.get("anyOf", [])]
    types = [t for t in types if t and t != "null"]
    item = _resolve(spec, raw.get("items", {})) if raw.get("items") else {}
    enum = raw.get("enum") or next((x.get("enum") for x in raw.get("anyOf", []) if isinstance(x, dict) and x.get("enum")), None)
    return {"name": name, "type": types[0] if types else "string", "items": item.get("type"),
            "enum": enum, "default": raw.get("default"), "minimum": raw.get("minimum"), "maximum": raw.get("maximum"),
            "max_items": raw.get("maxItems"), "max_length": raw.get("maxLength"),
            "description": (raw.get("description") or "").strip(),
            "required": name in required}


def _finish(provider: str, model: str, title: str, category: str, fields: list[dict]) -> dict:
    roles = {}
    names = {f["name"] for f in fields}
    for role, cands in ROLE_NAMES.items():
        hit = next((c for c in cands if c in names), None)
        if hit:
            roles[role] = hit
    if "first_frame" in roles and roles["first_frame"] == roles.get("ref_images"):
        roles.pop("first_frame")
    text = " ".join(f["description"] for f in fields)
    syntax = "@Image{n}" if "@Image" in text else "[Image {n}]" if "[Image" in text else None
    return {"schema_version": 1, "provider": provider, "model": model, "title": title, "category": category,
            "inputs": fields, "roles": roles, "ref_syntax": syntax, "fetched": int(time.time())}


def fal_manifest(model: str) -> dict:
    r = requests.get("https://api.fal.ai/v1/models", params={"endpoint_id": model, "expand": "openapi-3.0"},
                     headers=UA, timeout=30)
    r.raise_for_status()
    items = r.json().get("models") or []
    m = next((x for x in items if x.get("endpoint_id") == model), None)
    if not m or not m.get("openapi"):
        raise SystemExit(f"fal model not found: {model}")
    spec = m["openapi"]
    post = next(v["post"] for p, v in spec["paths"].items() if "post" in v and "{request_id}" not in p)
    schema = _resolve(spec, post["requestBody"]["content"]["application/json"]["schema"])
    req = set(schema.get("required", []))
    fields = [_field(spec, k, v, req) for k, v in schema.get("properties", {}).items()]
    meta = m.get("metadata", {})
    return _finish("fal", model, meta.get("display_name", model), meta.get("category", ""), fields)


def _kie_index() -> list[dict]:
    t = requests.get("https://docs.kie.ai/llms.txt", headers=UA, timeout=30).text
    out = []
    for line in t.splitlines():
        m = re.match(r"- (Video|Image)\s+Models > ([^\[]+)\[([^\]]+)\]\((https://docs\.kie\.ai/market/[^)]+\.md)\)", line)
        if m and "/cn/" not in m.group(4):
            out.append({"kind": m.group(1).lower(), "family": m.group(2).strip(), "title": m.group(3).strip(), "doc": m.group(4)})
    return out


def kie_manifest(model: str, doc: str | None = None) -> dict:
    import yaml
    if not doc:
        direct = f"https://docs.kie.ai/market/{model}.md"
        if requests.head(direct, headers=UA, timeout=20, allow_redirects=True).status_code == 200:
            doc = direct
        else:
            doc = next((e["doc"] for e in _kie_index() if _slug_from_doc(e["doc"]) == model
                        or model.replace("/", "-") in e["doc"]), None)
        if not doc:
            raise SystemExit(f"Kie model not found: {model}")
    md = requests.get(doc, headers=UA, timeout=30).text
    spec = yaml.safe_load(re.search(r"```yaml\n(.*?)```", md, re.S).group(1))
    body = spec["paths"]["/api/v1/jobs/createTask"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    model_id = (body["properties"]["model"].get("enum") or [model])[0]
    inp = body["properties"]["input"]
    req = set(inp.get("required", []))
    fields = [_field(spec, k, v, req) for k, v in inp.get("properties", {}).items()]
    title = md.splitlines()[0].lstrip("# ").strip()
    return _finish("kie", model_id, title, "", fields)


def _g(name, typ, desc, enum=None, default=None, items=None, max_items=None, required=False):
    return {"name": name, "type": typ, "items": items, "enum": enum, "default": default, "minimum": None, "maximum": None,
            "max_items": max_items, "max_length": None, "description": desc, "required": required}


def google_manifest(model: str) -> dict:
    """Gemini API models (per ai.google.dev docs, Sept 2026). Media is sent inline, so refs are local files."""
    if model.startswith("veo-"):
        lite = "lite" in model
        fields = [
            _g("prompt", "string", "What happens in the video. Veo also follows sound cues in quotes; PULSEFRAME mutes model audio.", required=True),
            _g("negative_prompt", "string", "What to avoid."),
            _g("image_url", "string", "First frame image (image-to-video)."),
            _g("last_frame_url", "string", "Last frame image; Veo interpolates between first and last frame."),
            _g("reference_image_urls", "array", "Up to 3 asset reference images for characters, objects or style.", items="string", max_items=3),
            _g("aspect_ratio", "string", "Frame shape.", enum=["16:9", "9:16"], default="16:9"),
            _g("resolution", "string", "Output resolution.", enum=["720p", "1080p"] + ([] if lite else ["4k"]), default="720p"),
            _g("duration", "string", "Length in seconds.", enum=["4", "6", "8"], default="8"),
            _g("person_generation", "string", "People in the video.", enum=["allow_adult", "allow_all"], default="allow_adult"),
            _g("seed", "integer", "Fix for repeatable results."),
        ]
        title = {"veo-3.1-generate-preview": "Veo 3.1", "veo-3.1-fast-generate-preview": "Veo 3.1 Fast",
                 "veo-3.1-lite-generate-preview": "Veo 3.1 Lite"}.get(model, model)
        return _finish("google", model, title, "video", fields)
    fields = [
        _g("prompt", "string", "What the image shows.", required=True),
        _g("image_urls", "array", "Reference images (characters, style, the previous shot).", items="string", max_items=14),
        _g("aspect_ratio", "string", "Frame shape.", enum=["1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"], default="16:9"),
        _g("image_size", "string", "Output size.", enum=(["1K"] if "lite" in model else ["1K", "2K", "4K"]), default="1K"),
    ]
    title = {"gemini-3.1-flash-image": "Nano Banana (Gemini 3.1 Flash Image)", "gemini-3-pro-image": "Nano Banana Pro (Gemini 3 Pro Image)",
             "gemini-3.1-flash-lite-image": "Gemini 3.1 Flash Lite Image"}.get(model, model)
    return _finish("google", model, title, "image", fields)


GOOGLE_MODELS = [
    ("veo-3.1-generate-preview", "video"), ("veo-3.1-fast-generate-preview", "video"), ("veo-3.1-lite-generate-preview", "video"),
    ("gemini-3.1-flash-image", "image"), ("gemini-3-pro-image", "image"), ("gemini-3.1-flash-lite-image", "image"),
]

def manifest(provider: str, model: str, refresh: bool = False) -> dict:
    if provider == "google":
        return google_manifest(model)
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{provider}__{re.sub(r'[^A-Za-z0-9._-]+', '_', model)}.json")
    if not refresh and os.path.exists(path) and time.time() - os.path.getmtime(path) < 7 * 86400:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        # Recompute roles so improvements to role detection apply to cached schemas too.
        return {**_finish(m["provider"], m["model"], m["title"], m.get("category", ""), m["inputs"]), "fetched": m.get("fetched")}
    m = fal_manifest(model) if provider == "fal" else kie_manifest(model)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1, ensure_ascii=False)
    return m


FAL_CATEGORIES = {"video": ("image-to-video", "text-to-video", "video-to-video"),
                  "image": ("text-to-image", "image-to-image"),
                  "lipsync": ("video-to-video", "audio-to-video")}


def catalog(provider: str, kind: str = "video") -> list[dict]:
    """Models a user can pick in Director Mode (kind: video | image | lipsync)."""
    if provider == "google":
        return [{"provider": "google", "model": m, "category": k, "title": google_manifest(m)["title"]}
                for m, k in GOOGLE_MODELS if k == kind]
    if provider == "fal":
        out, seen = [], set()
        for cat in FAL_CATEGORIES.get(kind, FAL_CATEGORIES["video"]):
            cursor = None
            for _ in range(10):
                params = {"category": cat, "limit": 100, "status": "active"}
                if cursor:
                    params["cursor"] = cursor
                r = requests.get("https://api.fal.ai/v1/models", params=params, headers=UA, timeout=30).json()
                for m in r.get("models", []):
                    if m["endpoint_id"] not in seen:
                        seen.add(m["endpoint_id"])
                        out.append({"provider": "fal", "model": m["endpoint_id"], "category": cat,
                                    "title": m.get("metadata", {}).get("display_name", m["endpoint_id"])})
                cursor = r.get("next_cursor")
                if not r.get("has_more") or not cursor:
                    break
        if kind == "lipsync":
            out = [m for m in out if re.search(r"lip.?sync|sync-|talking|avatar", m["model"] + m["title"], re.I)]
        return out
    return [{"provider": "kie", "model": _slug_from_doc(e["doc"]), "category": e["kind"], "title": f"{e['family']} · {e['title']}",
             "doc": e["doc"]} for e in _kie_index()
            if (e["kind"] == kind) or (kind == "lipsync" and re.search(r"lip.?sync|avatar|infinitalk", e["doc"] + e["title"], re.I))]


def _slug_from_doc(doc: str) -> str:
    # docs.kie.ai/market/bytedance/seedance-2.md -> bytedance/seedance-2 (matches Kie ids for most models;
    # the manifest fetch reads the exact id from the doc's schema).
    return doc.split("/market/")[1].removesuffix(".md")


# ---------------------------------------------------------------- looks

STYLES_PATH = os.path.join(os.path.dirname(__file__), "styles.json")


def styles() -> dict[str, dict]:
    with open(STYLES_PATH, encoding="utf-8") as f:
        return {s["id"]: s for s in json.load(f)["styles"]}


def resolve_look(project: dict) -> dict:
    """Project look -> {'id', 'prompt', 'avoid'}. Custom wording (Director Mode) overrides the library's."""
    look = project.get("look") or {"style": "auto"}
    if isinstance(look, str):  # early projects stored free text
        return {"id": "custom", "prompt": look, "avoid": ""}
    base = styles().get(look.get("style", "auto"), styles()["auto"])
    prompt = look.get("prompt") or base["prompt"]
    if look.get("notes"):
        prompt = f"{prompt} {look['notes'].strip()}"
    return {"id": base["id"], "prompt": prompt, "avoid": look.get("avoid") if look.get("avoid") is not None else base["avoid"]}


# ---------------------------------------------------------------- compile: Shot Contract -> request

def _nearest_aspect(options: list[str] | None, ratio: float) -> str | None:
    if not options:
        return None
    best, err = None, 9e9
    for o in options:
        m = re.match(r"^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$", str(o))
        if m and abs(float(m.group(1)) / float(m.group(2)) - ratio) < err:
            best, err = o, abs(float(m.group(1)) / float(m.group(2)) - ratio)
    return best


def _duration_value(field: dict, need: float):
    """Smallest allowed duration >= shot length + a short handle for trimming on the beat."""
    want = need + 0.5
    if field.get("enum"):
        nums = sorted(float(e) for e in field["enum"] if re.match(r"^\d+(\.\d+)?s?$", str(e).rstrip("s")))
        pick = next((n for n in nums if n >= want), nums[-1] if nums else None)
        if pick is None:
            return field.get("default")
        raw = next(e for e in field["enum"] if re.match(r"^\d", str(e)) and float(str(e).rstrip("s")) == pick)
        return raw
    lo = field.get("minimum") or 4
    hi = field.get("maximum") or 15
    m = re.search(r"(\d+)\s*-\s*(\d+)\s*sec", field.get("description", ""))
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
    val = int(min(hi, max(lo, math.ceil(want))))
    return val if field["type"] == "integer" else str(val) if field["type"] == "string" else val


INTENSITY = [(3, "restrained, almost still, the feeling held just under the surface"),
             (6, "grounded and natural, clearly felt but never pushed"),
             (8, "heightened and visible, the emotion driving the body"),
             (11, "at full intensity, the emotion overwhelming control")]
QUALITY_TIERS = ("draft", "standard", "high", "max")


def _intensity_words(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    return next(w for lim, w in INTENSITY if n < lim)


def _character(plan: dict, name: str) -> dict:
    return next((c for c in plan.get("characters", []) if c.get("name", "").lower() == name.lower()), {})


def acting_direction(shot: dict, plan: dict) -> str:
    """Actor-language direction for the performance, the part video models most often get wrong.

    Combines the shot's directed performance (emotion, intensity, intention, body, face, gaze, movement)
    with each performer's standing acting notes from the character bible.
    """
    lines = []
    emotion, level = shot.get("emotion"), _intensity_words(shot.get("performance_intensity"))
    if emotion or level:
        lines.append(f"Emotion: {emotion or 'as the moment requires'}" + (f", played {level}" if level else "") + ".")
    if shot.get("performance"):
        lines.append(f"Performance: {shot['performance'].rstrip('.')}.")
    if shot.get("expression"):
        lines.append(f"Face: {shot['expression'].rstrip('.')}.")
    if shot.get("movement"):
        lines.append(f"Body and blocking: {shot['movement'].rstrip('.')}.")
    for name in shot.get("performers", []):
        notes = _character(plan, name).get("acting_notes")
        if notes:
            lines.append(f"{name}'s acting style: {notes.strip().rstrip('.')}.")
    if lines:
        lines.append("Play it truthfully: motivated small gestures, eyes that think before they move, "
                     "breathing that matches the emotion; no mugging or exaggerated poses.")
    return " ".join(lines)


def _pick_quality(field: dict, tier: str):
    """Map a project quality tier onto the model's own resolution options."""
    opts = field.get("enum") or []

    def height(o):
        if str(o).lower() in ("4k", "2160p"):
            return 2160
        m = re.search(r"(\d{3,4})", str(o))
        return int(m.group(1)) if m else 0

    ranked = sorted((o for o in opts if height(o)), key=height)
    if not ranked:
        return field.get("default")
    if tier == "draft":
        return ranked[0]
    if tier == "max":
        return ranked[-1]
    want = 1080 if tier == "high" else 720
    return min(ranked, key=lambda o: (abs(height(o) - want), -height(o)))


def compile_request(shot: dict, scene: dict | None, plan: dict, project: dict, man: dict,
                    refs: list[dict], overrides: dict | None = None, fix_notes: list[str] | None = None,
                    sung: dict | None = None) -> dict:
    """Shot Contract -> this model's request.

    refs: reference images already uploaded [{'label', 'url'}]. sung: optional lip-sync audio
    {'url', 'lyrics', 'performer'} for shots where a character sings.
    """
    roles, fields = man["roles"], {f["name"]: f for f in man["inputs"]}
    payload: dict = {}
    style = plan.get("meta", {}).get("VISUAL STYLE", "")
    look = resolve_look(project)  # the same look wording goes into every shot of the project
    blocks: list[tuple[int, str]] = []  # (priority, text); lowest priority is dropped first if too long

    body = shot.get("visual_prompt") or " ".join(shot.get("beats", [])) or shot.get("description", "")
    if "duration" not in roles:  # an image model: this is the shot's first frame
        # Image models weight the opening words most, so the look leads.
        lead = look["prompt"].split(":")[0].rstrip(".")
        body = f"{lead}. A single still, the first frame of this shot, in exactly that style: " + body
    blocks.append((10, body.strip()))
    if shot.get("performers"):
        blocks.append((9, f"Characters: {', '.join(shot['performers'])}."))
    acting = acting_direction(shot, plan)
    if acting:
        blocks.append((8, acting))
    cam = [shot.get("framing"), shot.get("lens"), shot.get("camera_movement") or ", ".join(shot.get("camera_moves", []))]
    cam = [c for c in cam if c]
    if cam:
        energy = f"; {shot['camera_energy']} energy" if shot.get("camera_energy") else ""
        blocks.append((7, "Camera: " + "; ".join(cam) + energy + "."))
    if shot.get("environment"):
        blocks.append((5, f"Setting: {shot['environment'].rstrip('.')}."))
    if shot.get("lighting"):
        blocks.append((6, f"Lighting: {shot['lighting'].rstrip('.')}."))
    if shot.get("wardrobe"):
        blocks.append((6, f"Wardrobe: {shot['wardrobe'].rstrip('.')}."))
    blocks.append((9, f"Look: {look['prompt']}"))
    if style:
        blocks.append((3, f"Mood and colour: {style}"))

    image_refs = refs[: fields[roles["ref_images"]].get("max_items") or len(refs)] if "ref_images" in roles else []
    if image_refs:
        ordinal = ["first", "second", "third", "fourth", "fifth", "sixth"]
        tags = [f"{man['ref_syntax'].format(n=i + 1)} is the {r['label']}" if man.get("ref_syntax")
                else f"the {ordinal[min(i, 5)]} reference image is the {r['label']}" for i, r in enumerate(image_refs)]
        blocks.append((9, "References: " + "; ".join(tags) + ". Match the characters' faces, hair and wardrobe exactly."))

    lip = bool(sung and "ref_audio" in roles and project.get("lip_sync", "auto") != "off")
    if lip:
        tag = "@Audio1" if man.get("ref_syntax") == "@Image{n}" else "the reference audio"
        lyric = " / ".join(sung.get("lyrics", []))
        blocks.append((9, f"{sung['performer']} sings along to {tag}: \"{lyric}\". Mouth shapes, breaths and phrasing "
                          f"follow the vocal exactly; the performance is felt, not mimed."))
    if look["avoid"] and "negative_prompt" not in roles:
        blocks.append((4, f"Avoid: {look['avoid']}."))
    if fix_notes:
        blocks.append((10, "Corrections from review: " + " ".join(n.rstrip(".") + "." for n in fix_notes)))
    if "duration" not in roles:
        blocks.append((9, "A clean, uncluttered cinematic frame with nothing written anywhere in the image."))
    else:
        blocks.append((9, "No on-screen text, no subtitles, no watermark." + ("" if lip else " Performers do not lip-sync.")))

    limit = (fields.get(roles.get("prompt", "prompt")) or {}).get("max_length") or 0
    keep = set(range(len(blocks)))
    drop_order = sorted(range(len(blocks)), key=lambda i: blocks[i][0])

    def text() -> str:
        return " ".join(blocks[i][1] for i in sorted(keep))

    while limit and len(text()) > limit and drop_order:
        keep.discard(drop_order.pop(0))
    payload[roles.get("prompt", "prompt")] = text()[:limit] if limit else text()

    keyframe = next((r["url"] for r in refs if r.get("keyframe")), None)
    if keyframe and "first_frame" in roles:
        payload[roles["first_frame"]] = keyframe
        image_refs = [r for r in image_refs if not r.get("keyframe")]
    if image_refs:
        f = fields[roles["ref_images"]]
        urls = [r["url"] for r in image_refs]
        payload[f["name"]] = urls if f["type"] == "array" else urls[0]
    elif refs and "first_frame" in roles and "first_frame" not in [k for k in roles if roles[k] in payload]:
        payload[roles["first_frame"]] = refs[0]["url"]
    if lip:
        f = fields[roles["ref_audio"]]
        payload[f["name"]] = [sung["url"]] if f["type"] == "array" else sung["url"]
    if "duration" in roles:
        payload[roles["duration"]] = _duration_value(fields[roles["duration"]], shot["end"] - shot["start"])
    if "aspect_ratio" in roles:
        ar = project.get("aspect_ratio", "16:9")
        m = re.match(r"^([\d.]+):([\d.]+)$", ar)
        ratio = float(m.group(1)) / float(m.group(2)) if m else 16 / 9
        pick = _nearest_aspect(fields[roles["aspect_ratio"]].get("enum"), ratio)
        if pick:
            payload[roles["aspect_ratio"]] = pick
    if "resolution" in roles:
        payload[roles["resolution"]] = _pick_quality(fields[roles["resolution"]], project.get("quality", "standard"))
    if project.get("quality") == "max" and "bitrate_mode" in fields and "high" in (fields["bitrate_mode"].get("enum") or []):
        payload["bitrate_mode"] = "high"
    if look["avoid"] and "negative_prompt" in roles:
        payload[roles["negative_prompt"]] = f"{look['avoid']}, text, subtitles, watermark"
    if "audio" in roles:
        payload[roles["audio"]] = False  # the song is the master audio track (PRD §3)
    for k, v in (overrides or {}).items():  # Director Mode pins always win
        if k in fields:
            payload[k] = v
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------- providers

class Fal:
    name = "fal"

    def __init__(self):
        self.key = os.environ.get("FAL_KEY")
        if not self.key:
            raise SystemExit("Add your fal.ai key in Settings to render with fal.")
        self.h = {**UA, "Authorization": f"Key {self.key}", "Content-Type": "application/json"}

    def upload(self, path: str) -> str:
        import fal_client
        return fal_client.upload_file(path)

    def submit(self, model: str, payload: dict) -> dict:
        r = requests.post(f"https://queue.fal.run/{model}", json=payload, headers=self.h, timeout=60)
        _raise(r)
        j = r.json()
        return {"id": j["request_id"], "status_url": j.get("status_url"), "response_url": j.get("response_url")}

    def poll(self, model: str, rid: str, meta: dict | None = None) -> dict:
        base = f"https://queue.fal.run/{_fal_app(model)}/requests/{rid}"
        status_url = (meta or {}).get("status_url") or base + "/status"
        response_url = (meta or {}).get("response_url") or base
        s = requests.get(status_url, headers=self.h, timeout=30)
        _raise(s)
        st = s.json()
        if st.get("status") != "COMPLETED":
            return {"state": "running", "detail": st.get("status", "").replace("_", " ").lower(),
                    "queue_position": st.get("queue_position")}
        r = requests.get(response_url, headers=self.h, timeout=60)
        if r.status_code >= 400:
            return {"state": "failed", "error": _err_text(r)}
        url = _find_media_url(r.json())
        return {"state": "done", "url": url} if url else {"state": "failed", "error": "No video in the result."}


def _fal_app(model: str) -> str:
    # Queue status/result live under the app id: owner/app (first two path segments).
    return "/".join(model.split("/")[:2])


class Kie:
    name = "kie"
    base = "https://api.kie.ai/api/v1/jobs"

    def __init__(self):
        self.key = os.environ.get("KIE_KEY")
        if not self.key:
            raise SystemExit("Add your Kie.ai key in Settings to render with Kie.")
        self.h = {**UA, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    def upload(self, path: str) -> str:
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            data = f"data:{mime};base64," + base64.b64encode(f.read()).decode()
        r = requests.post("https://kieai.redpandaai.co/api/file-base64-upload", headers=self.h, timeout=120,
                          json={"base64Data": data, "uploadPath": "pulseframe", "fileName": os.path.basename(path)})
        _raise(r)
        j = r.json()
        d = j.get("data", j)
        url = d.get("downloadUrl") or d.get("fileUrl") or d.get("url")
        if not url:
            raise RuntimeError(f"Kie upload returned no URL: {str(j)[:200]}")
        return url

    def submit(self, model: str, payload: dict) -> dict:
        r = requests.post(f"{self.base}/createTask", json={"model": model, "input": payload}, headers=self.h, timeout=60)
        _raise(r)
        j = r.json()
        if j.get("code") not in (200, None) or not (j.get("data") or {}).get("taskId"):
            raise RuntimeError(j.get("msg") or str(j)[:200])
        return {"id": j["data"]["taskId"]}

    def poll(self, model: str, rid: str, meta: dict | None = None) -> dict:
        r = requests.get(f"{self.base}/recordInfo", params={"taskId": rid}, headers=self.h, timeout=30)
        _raise(r)
        d = r.json().get("data") or {}
        st = d.get("state")
        if st == "success":
            res = json.loads(d.get("resultJson") or "{}")
            urls = res.get("resultUrls") or []
            return {"state": "done", "url": urls[0] if urls else None, "cost": d.get("creditsConsumed"),
                    "cost_unit": "credits"} if urls else {"state": "failed", "error": "No video in the result."}
        if st == "fail":
            return {"state": "failed", "error": d.get("failMsg") or d.get("failCode") or "Generation failed."}
        return {"state": "running", "detail": st or "waiting", "progress": d.get("progress")}


class Google:
    """Gemini API: Veo (long-running) and Gemini image models (synchronous). Media goes inline as base64."""
    name = "google"
    base = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self):
        self.key = os.environ.get("GEMINI_API_KEY")
        if not self.key:
            raise SystemExit("Add your Google Gemini API key in Settings to render with Google.")
        self.h = {**UA, "x-goog-api-key": self.key, "Content-Type": "application/json"}

    def upload(self, path: str) -> str:
        # No upload service for these endpoints: keep a local reference and inline it at submit time.
        return "file:" + os.path.abspath(path)

    @staticmethod
    def _inline(ref: str) -> dict:
        path = ref[5:] if ref.startswith("file:") else ref
        mime = mimetypes.guess_type(path)[0] or "image/png"
        with open(path, "rb") as f:
            return {"mimeType": mime, "data": base64.b64encode(f.read()).decode()}

    def submit(self, model: str, payload: dict) -> dict:
        if model.startswith("veo-"):
            inst: dict = {"prompt": payload.get("prompt", "")}
            if payload.get("image_url"):
                inst["image"] = {"inlineData": self._inline(payload["image_url"])}
            if payload.get("last_frame_url"):
                inst["lastFrame"] = {"inlineData": self._inline(payload["last_frame_url"])}
            if payload.get("reference_image_urls"):
                inst["referenceImages"] = [{"image": {"inlineData": self._inline(u)}, "referenceType": "asset"}
                                           for u in payload["reference_image_urls"][:3]]
            params = {k2: payload[k1] for k1, k2 in (("aspect_ratio", "aspectRatio"), ("resolution", "resolution"),
                                                      ("duration", "durationSeconds"), ("negative_prompt", "negativePrompt"),
                                                      ("person_generation", "personGeneration"), ("seed", "seed")) if payload.get(k1) not in (None, "")}
            r = requests.post(f"{self.base}/models/{model}:predictLongRunning", json={"instances": [inst], "parameters": params},
                              headers=self.h, timeout=120)
            _raise(r)
            return {"id": r.json()["name"]}
        # Image models answer immediately; keep the bytes until the runner downloads them.
        inputs = [{"type": "text", "text": payload.get("prompt", "")}]
        for u in payload.get("image_urls") or []:
            d = self._inline(u)
            inputs.append({"type": "image", "mime_type": d["mimeType"], "data": d["data"]})
        body = {"model": model, "input": inputs, "response_format": {"type": "image", "mime_type": "image/png",
                **({"aspect_ratio": payload["aspect_ratio"]} if payload.get("aspect_ratio") else {}),
                **({"image_size": payload["image_size"]} if payload.get("image_size") else {})}}
        r = requests.post(f"{self.base}/interactions", json=body, headers=self.h, timeout=300)
        _raise(r)
        j = r.json()
        it = j.get("interaction", j)
        data = (it.get("output_image") or {}).get("data") or next(
            (c.get("data") for st in it.get("steps", []) for c in st.get("content", []) if c.get("type") == "image" and c.get("data")), None)
        if not data:
            raise ProviderError("Google returned no image (it may have been blocked by safety filters).", 422)
        tmp = os.path.join(os.path.expanduser("~"), ".pulseframe", "incoming")
        os.makedirs(tmp, exist_ok=True)
        path = os.path.join(tmp, f"{uuid.uuid4().hex}.png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        return {"id": "inline-" + os.path.basename(path), "file": path}

    def poll(self, model: str, rid: str, meta: dict | None = None) -> dict:
        if rid.startswith("inline-"):
            return {"state": "done", "url": "file:" + (meta or {}).get("file", "")}
        r = requests.get(f"{self.base}/{rid}", headers=self.h, timeout=30)
        _raise(r)
        op = r.json()
        if not op.get("done"):
            return {"state": "running", "detail": "generating"}
        if op.get("error"):
            return {"state": "failed", "error": op["error"].get("message", "Generation failed.")}
        samples = ((op.get("response") or {}).get("generateVideoResponse") or {}).get("generatedSamples") or []
        uri = samples[0]["video"]["uri"] if samples else None
        return {"state": "done", "url": uri, "auth": True} if uri else {"state": "failed", "error": "No video returned (possibly blocked by safety filters)."}


PROVIDERS = {"fal": Fal, "kie": Kie, "google": Google}


class ProviderError(RuntimeError):
    def __init__(self, msg: str, status: int):
        super().__init__(msg)
        self.status = status


def _err_text(r: requests.Response) -> str:
    try:
        j = r.json()
        d = j.get("detail") or j.get("msg") or j.get("message") or j
        if isinstance(d, list):
            d = "; ".join(str(x.get("msg", x)) if isinstance(x, dict) else str(x) for x in d)
        return f"{r.status_code}: {str(d)[:400]}"
    except ValueError:
        return f"{r.status_code}: {r.text[:300]}"


def _raise(r: requests.Response) -> None:
    if r.status_code >= 400:
        raise ProviderError(_err_text(r), r.status_code)


def _find_media_url(obj) -> str | None:
    if isinstance(obj, dict):
        for k in ("video", "videos", "output", "result"):
            if k in obj:
                u = _find_media_url(obj[k])
                if u:
                    return u
        if isinstance(obj.get("url"), str):
            return obj["url"]
        for v in obj.values():
            u = _find_media_url(v)
            if u:
                return u
    elif isinstance(obj, list):
        for v in obj:
            u = _find_media_url(v)
            if u:
                return u
    elif isinstance(obj, str) and obj.startswith("http") and re.search(r"\.(mp4|mov|webm)(\?|$)", obj):
        return obj
    return None


# ---------------------------------------------------------------- project job store

def _read(path: str, default):
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


class Store:
    def __init__(self, project_dir: str):
        self.dir = project_dir
        self.path = os.path.join(project_dir, "jobs.json")
        self.data = _read(self.path, {"schema_version": 1, "jobs": []})

    @property
    def jobs(self) -> list[dict]:
        return self.data["jobs"]

    def save(self) -> None:
        _write(self.path, self.data)

    def update(self, job: dict, **kw) -> None:
        job.update(kw, updated=int(time.time()))
        self.save()
        emit(event="job", job=job)


def _load_plan(d: str) -> tuple[str, dict]:
    for name in ("directed", "production"):
        p = _read(os.path.join(d, f"{name}.json"), None)
        if p:
            return name, p
    raise SystemExit("This project has no shot plan yet.")


def _shot(plan: dict, shot_id: str) -> tuple[dict, dict]:
    for sc in plan["scenes"]:
        for sh in sc["shots"]:
            if sh["id"] == shot_id:
                return sh, sc
    raise SystemExit(f"Shot {shot_id} not found.")


def _reference_files(d: str, project: dict, shot: dict | None = None) -> list[dict]:
    """Reference images for a shot: a clean image per performer when the project has them (so only the
    people in the shot are sent, without sheet text to copy), else the whole character sheet; then the set sheet."""
    refs = project.get("references") or {}
    out = []
    cast = refs.get("cast") or {}
    people = (shot or {}).get("performers") or []
    picked = [n for n in people if cast.get(n) and os.path.exists(os.path.join(d, cast[n]))]
    if picked:
        for n in picked:
            out.append({"label": f"reference for {n} (face, expressions, full-body turnaround)", "path": os.path.join(d, cast[n])})
    elif refs.get("characters") and os.path.exists(os.path.join(d, refs["characters"])):
        out.append({"label": "character sheet (faces, turnarounds, outfits)", "path": os.path.join(d, refs["characters"])})
    if refs.get("sets") and os.path.exists(os.path.join(d, refs["sets"])):
        out.append({"label": "set and props sheet (locations, props, colour palette)", "path": os.path.join(d, refs["sets"])})
    return out


def _uploaded(d: str, provider, files: list[dict]) -> list[dict]:
    """Upload reference images once per provider; reuse URLs until they are close to expiring."""
    cache_path = os.path.join(d, "cache", "uploads.json")
    cache = _read(cache_path, {})
    ttl = 2 * 86400 if provider.name == "kie" else 6 * 86400
    out = []
    for f in files:
        with open(f["path"], "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()[:16]
        key = f"{provider.name}:{digest}"
        hit = cache.get(key)
        if not hit or time.time() - hit["at"] > ttl:
            emit(event="progress", stage=f"uploading {os.path.basename(f['path'])}")
            hit = {"url": provider.upload(f["path"]), "at": int(time.time())}
            cache[key] = hit
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            _write(cache_path, cache)
        out.append({"label": f["label"], "url": hit["url"]})
    return out


# ---------------------------------------------------------------- lip-sync audio

SING_WORDS = re.compile(r"\b(sing|sings|singing|sung|vocal|lip|mouths?|chorus|verse|lyric)", re.I)


def singing(d: str, shot: dict, plan: dict) -> dict | None:
    """If a performer sings in this shot, the lyric lines under it and who sings them."""
    song_map = _read(os.path.join(d, "songmap.json"), {}) or {}
    lines = [l for l in song_map.get("lyrics", []) if l.get("start") is not None
             and l["start"] < shot["end"] and (l.get("end") or l["start"]) > shot["start"]]
    if not lines or not shot.get("performers"):
        return None
    text = " ".join(str(shot.get(k, "")) for k in ("visual_prompt", "performance", "movement", "description")) + " ".join(shot.get("beats", []))
    if not SING_WORDS.search(text):
        return None
    lead = (plan.get("characters") or [{}])[0].get("name")
    singer = lead if lead in shot["performers"] else shot["performers"][0]
    return {"performer": singer, "lyrics": [l["text"] for l in lines]}


def _vocal_stem(d: str) -> str | None:
    """Isolated vocals from song analysis (Demucs), if available."""
    stems = os.path.join(d, "cache", "stems", "htdemucs")
    if os.path.isdir(stems):
        for sub in os.listdir(stems):
            v = os.path.join(stems, sub, "vocals.wav")
            if os.path.exists(v):
                return v
    return None


CLOSE = re.compile(r"close|tight|\bcu\b|ecu|mcu|portrait|head and shoulders", re.I)


def is_closeup(shot: dict) -> bool:
    return bool(CLOSE.search(f"{shot.get('framing', '')} {shot.get('lens', '')}"))


def wants_lipsync_pass(d: str, project: dict, plan: dict, shot: dict) -> bool:
    """Project rule 'closeups': singing close-ups get a dedicated lip-sync pass after rendering."""
    return project.get("lip_sync") == "closeups" and is_closeup(shot) and bool(singing(d, shot, plan))


def _lipsync_provider() -> str | None:
    return "fal" if os.environ.get("FAL_KEY") else "kie" if os.environ.get("KIE_KEY") else None


def song_slice(d: str, shot: dict, seconds: float, vocals_only: bool = False) -> str:
    """The exact piece of the song under this shot as a small mp3 (full mix, or the isolated vocal)."""
    import subprocess
    from .export import NO_WINDOW, ffmpeg
    project = _read(os.path.join(d, "project.json"), {})
    src = (_vocal_stem(d) if vocals_only else None) or os.path.join(d, project.get("song", "song.wav"))
    out_dir = os.path.join(d, "cache", "lipsync")
    os.makedirs(out_dir, exist_ok=True)
    tag = "vox" if src != os.path.join(d, project.get("song", "song.wav")) else "mix"
    out = os.path.join(out_dir, f"{shot['id']}_{shot['start']:.3f}_{seconds:.2f}_{tag}.mp3")
    if not os.path.exists(out):
        subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{shot['start']:.3f}", "-t", f"{seconds:.3f}",
                        "-i", src, "-ac", "2", "-b:a", "192k", out], check=True, creationflags=NO_WINDOW)
    return out


def take_duration(path: str) -> float:
    import subprocess
    from .export import NO_WINDOW, ffmpeg
    err = subprocess.run([ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True, creationflags=NO_WINDOW).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def compile_lipsync(d: str, man: dict, shot: dict, source: dict, overrides: dict | None) -> dict:
    """Lip-sync pass request: the source take plus the isolated vocal under the shot, same length."""
    roles = man["roles"]
    if "src_video" not in roles or "src_audio" not in roles:
        raise SystemExit(f"{man['title']} doesn't take a video and an audio track, so it can't lip-sync a take.")
    take = os.path.join(d, source["output"])
    seconds = take_duration(take) or (shot["end"] - shot["start"])
    payload = {roles["src_video"]: PROJECT_MEDIA + source["output"],
               roles["src_audio"]: PROJECT_MEDIA + os.path.relpath(song_slice(d, shot, seconds, vocals_only=True), d).replace(os.sep, "/")}
    fields = {f["name"]: f for f in man["inputs"]}
    if "sync_mode" in fields:
        payload["sync_mode"] = "cut_off"
    if "separate_vocal" in fields and not _vocal_stem(d):
        payload["separate_vocal"] = True
    for k, v in (overrides or {}).items():
        if k in fields:
            payload[k] = v
    return payload


def enqueue(d: str, shot_ids: list[str], provider: str, model: str | None, overrides: dict | None,
            fix_notes: list[str] | None = None, kind: str = "video", source_job: str | None = None) -> list[dict]:
    project = _read(os.path.join(d, "project.json"), {})
    plan_name, plan = _load_plan(d)
    model = model or {"image": AUTO_IMAGE, "lipsync": AUTO_LIPSYNC}.get(kind, AUTO)[provider]
    if kind == "lipsync":
        src = next((j for j in Store(d).jobs if j["id"] == source_job and j["state"] == "ready" and j.get("output")), None)
        if not src:
            raise SystemExit("Choose a finished take to lip-sync.")
    man = manifest(provider, model)
    store = Store(d)
    made = []
    for sid in shot_ids:
        if any(j["shot_id"] == sid and j["plan"] == plan_name and j["provider"] == provider and j["model"] == man["model"]
               and j.get("kind", "video") == kind
               and j["state"] in ACTIVE for j in store.jobs):
            continue  # never double-queue the same shot on the same model (side-by-side comparisons are fine)
        shot, scene = _shot(plan, sid)
        job = {"id": uuid.uuid4().hex[:12], "shot_id": sid, "plan": plan_name, "source_shots": shot.get("source_shots", []),
               "shot_start": shot["start"], "shot_end": shot["end"], "provider": provider, "model": man["model"],
               "kind": kind, "source_job": source_job, "overrides": overrides or {}, "fix_notes": fix_notes or [], "look": resolve_look(project)["id"], "state": "queued", "provider_job_id": None, "attempts": 0,
               "created": int(time.time()), "updated": int(time.time()), "output": None, "error": None, "cost": None}
        store.jobs.append(job)
        made.append(job)
    store.save()
    for j in made:
        emit(event="job", job=j)
    return made


def run(d: str, poll_every: float = 6.0) -> None:
    """Drive every active job to completion. Safe to start again after a crash or restart."""
    store = Store(d)
    lock = os.path.join(d, "cache", "render.lock")
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    if os.path.exists(lock) and time.time() - os.path.getmtime(lock) < 60:
        emit(event="progress", stage="another renderer is already running for this project")
        return
    project = _read(os.path.join(d, "project.json"), {})
    providers: dict[str, object] = {}

    def prov(name):
        if name not in providers:
            providers[name] = PROVIDERS[name]()
        return providers[name]

    for j in store.jobs:  # crash recovery: a submit that never recorded its id may or may not exist remotely
        if j["state"] == "submitting":
            store.update(j, state="uncertain",
                         error="The app closed while this shot was being sent. It may already be rendering "
                               "(and billed). Check your provider dashboard before retrying.")
    try:
        while True:
            with open(lock, "w") as f:
                f.write(str(os.getpid()))
            active = [j for j in store.jobs if j["state"] in ACTIVE]
            if not active:
                break
            for j in active:
                try:
                    p = prov(j["provider"])
                    if j["state"] == "queued":
                        _submit(d, store, project, p, j)
                    elif j["state"] == "submitted":
                        _check(d, store, p, j)
                except SystemExit as e:  # missing key etc.
                    store.update(j, state="failed", error=str(e))
                except ProviderError as e:
                    if e.status in (429, 500, 502, 503, 504):
                        emit(event="progress", stage=f"{j['shot_id']}: provider busy, will retry")
                        continue
                    store.update(j, state="failed" if j["state"] != "submitting" else "uncertain", error=str(e))
                except requests.RequestException as e:  # network blip: keep the job, try next round
                    emit(event="progress", stage=f"{j['shot_id']}: network issue ({type(e).__name__}), retrying")
                    if j["state"] == "submitting":
                        store.update(j, state="uncertain", error=f"Lost connection while sending: {e}")
            if any(j["state"] == "submitted" for j in store.jobs):
                time.sleep(poll_every)
    finally:
        if os.path.exists(lock):
            os.remove(lock)
    review_pending(d)
    emit(event="progress", stage="all renders settled")


def _submit(d: str, store: Store, project: dict, p, j: dict) -> None:
    _, plan = _load_plan(d) if j["plan"] == "directed" else ("production", _read(os.path.join(d, "production.json"), {}))
    shot, scene = _shot(plan, j["shot_id"])
    man = manifest(j["provider"], j["model"])
    emit(event="progress", stage=f"preparing {j['shot_id']}")
    ref_files = _reference_files(d, project, shot)
    if j.get("kind") == "image":
        ref_files = [r for r in ref_files if not r["label"].startswith("set and props")]
    refs = [] if j.get("kind") == "lipsync" else _uploaded(d, p, ref_files)
    if j.get("kind") == "lipsync":
        src = next((x for x in store.jobs if x["id"] == j.get("source_job")), None)
        if not src or not src.get("output"):
            raise SystemExit("The take this lip-sync was based on is gone.")
        payload = compile_lipsync(d, man, shot, src, j.get("overrides"))
    else:
        sung = _sung_for(d, shot, plan, man, p) if j.get("kind", "video") == "video" else None
        if j.get("kind", "video") == "video":
            refs = _with_keyframe(refs, approved_keyframe(d, j["plan"], j["shot_id"]))
        payload = compile_request(shot, scene, plan, project, man, refs, j.get("overrides"), j.get("fix_notes"), sung)
    payload = _resolve_project_media(d, p, payload)
    # Persist intent BEFORE the billable call; the id is persisted the moment it returns.
    try:
        est = estimate_payload(j["provider"], j["model"], man, payload)
    except Exception:
        est = {"usd": None}
    store.update(j, state="submitting", payload=payload, attempts=j["attempts"] + 1, estimate_usd=est.get("usd"))
    emit(event="progress", stage=f"sending {j['shot_id']} to {j['provider']}")
    sub = p.submit(j["model"], payload)
    store.update(j, state="submitted", provider_job_id=sub.pop("id"), provider_meta=sub, submitted=int(time.time()))


def approved_keyframe(d: str, plan_name: str, shot_id: str) -> str | None:
    """The keyframe the user approved for this shot (a `project:` image), if any."""
    kf = _read(os.path.join(d, "keyframes.json"), {}) or {}
    ref = (kf.get(plan_name) or {}).get(shot_id)
    return ref if ref and os.path.exists(os.path.join(d, ref[len(PROJECT_MEDIA):])) else None


def _with_keyframe(refs: list[dict], kf: str | None) -> list[dict]:
    if not kf:
        return refs
    return [{"label": "approved keyframe for this exact shot: start from this frame and keep its composition, "
                      "characters, wardrobe and lighting", "url": kf, "keyframe": True}] + refs


def _sung_for(d: str, shot: dict, plan: dict, man: dict, provider=None) -> dict | None:
    """Lip-sync audio for singing shots on models that accept reference audio. provider=None: preview only."""
    project = _read(os.path.join(d, "project.json"), {})
    if "ref_audio" not in man["roles"] or project.get("lip_sync", "auto") == "off":
        return None
    sing = singing(d, shot, plan)
    if not sing:
        return None
    fields = {f["name"]: f for f in man["inputs"]}
    dur = shot["end"] - shot["start"]
    if "duration" in man["roles"]:
        try:
            dur = float(str(_duration_value(fields[man["roles"]["duration"]], dur)).rstrip("s"))
        except ValueError:
            pass
    local = song_slice(d, shot, dur)
    url = f"(upload) {os.path.basename(local)}" if provider is None else _upload_cached(d, provider, local)
    return {**sing, "url": url}


def _upload_cached(d: str, provider, path: str) -> str:
    return _uploaded(d, provider, [{"label": "", "path": path}])[0]["url"]


PROJECT_MEDIA = "project:"


def _resolve_project_media(d: str, provider, payload: dict) -> dict:
    """Director Mode uploads are stored in the project as `project:<relative path>`; upload them now."""
    def conv(v):
        if isinstance(v, str) and v.startswith(PROJECT_MEDIA):
            local = os.path.join(d, v[len(PROJECT_MEDIA):])
            if not os.path.exists(local):
                raise SystemExit(f"Reference file missing: {v[len(PROJECT_MEDIA):]}")
            return _upload_cached(d, provider, local)
        if isinstance(v, list):
            return [conv(x) for x in v]
        return v
    return {k: conv(v) for k, v in payload.items()}


def _check(d: str, store: Store, p, j: dict) -> None:
    res = p.poll(j["model"], j["provider_job_id"], j.get("provider_meta"))
    if res["state"] == "running":
        emit(event="progress", stage=f"rendering {j['shot_id']}", detail=res.get("detail"), job_id=j["id"])
        return
    if res["state"] == "failed":
        store.update(j, state="failed", error=res.get("error"))
        return
    out_dir = os.path.join(d, "generations")
    os.makedirs(out_dir, exist_ok=True)
    url = res["url"] or ""
    ext = ".mp4" if j.get("kind", "video") != "image" else (os.path.splitext(url.split("?")[0])[1].lower() or ".png")
    if ext not in (".mp4", ".mov", ".webm", ".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png" if j.get("kind") == "image" else ".mp4"
    out = os.path.join(out_dir, f"{j['shot_id']}__{j['id']}{ext}")
    emit(event="progress", stage=f"downloading {j['shot_id']}")
    if url.startswith("file:"):
        import shutil
        shutil.move(url[5:], out)
    else:
        headers = getattr(p, "h", {}) if res.get("auth") else {}
        with requests.get(url, stream=True, timeout=300, headers=headers) as r:
            r.raise_for_status()
            with open(out + ".part", "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        os.replace(out + ".part", out)
    store.update(j, state="ready", output=os.path.relpath(out, d).replace(os.sep, "/"), output_url=res["url"],
                 cost=res.get("cost"), cost_unit=res.get("cost_unit"), finished=int(time.time()))
    if j.get("kind", "video") in ("video", "lipsync"):
        _review(d, store, j)
    if j.get("kind", "video") == "video" and not j.get("lipsync_child"):
        _auto_lipsync(d, store, j)


def _auto_lipsync(d: str, store: Store, j: dict) -> None:
    project = _read(os.path.join(d, "project.json"), {})
    try:
        plan = _read(os.path.join(d, f"{j['plan']}.json"), {})
        shot, _ = _shot(plan, j["shot_id"])
    except SystemExit:
        return
    prov = _lipsync_provider()
    if not prov or not wants_lipsync_pass(d, project, plan, shot):
        return
    child = {"id": uuid.uuid4().hex[:12], "shot_id": j["shot_id"], "plan": j["plan"], "source_shots": j.get("source_shots", []),
             "shot_start": j["shot_start"], "shot_end": j["shot_end"], "provider": prov, "model": AUTO_LIPSYNC[prov],
             "kind": "lipsync", "source_job": j["id"], "auto": True, "overrides": {}, "fix_notes": [], "look": j.get("look"),
             "state": "queued", "provider_job_id": None, "attempts": 0, "created": int(time.time()), "updated": int(time.time()),
             "output": None, "error": None, "cost": None}
    store.jobs.append(child)
    store.update(j, lipsync_child=child["id"])
    emit(event="job", job=child)
    emit(event="progress", stage=f"{j['shot_id']} is a singing close-up: lip-sync pass queued")


def _review(d: str, store: Store, j: dict) -> None:
    from .review import review_job
    try:
        plan = _read(os.path.join(d, f"{j['plan']}.json"), {})
        shot, _ = _shot(plan, j["shot_id"])
    except SystemExit:
        return
    emit(event="progress", stage=f"reviewing {j['shot_id']}")
    try:
        store.update(j, review=review_job(d, j, _read(os.path.join(d, "project.json"), {}), shot))
    except Exception as e:
        store.update(j, review={"reviewed": False, "error": f"{type(e).__name__}: {e}"})


def review_pending(d: str) -> None:
    """Review finished takes that were never checked (e.g. an OpenAI key was added later)."""
    store = Store(d)
    can_see = bool(os.environ.get("PULSEFRAME_OPENAI_KEY"))
    for j in store.jobs:
        if j["state"] != "ready" or not j.get("output"):
            continue
        rv = j.get("review")
        never_checked = not rv or not rv.get("reviewed")
        # Upgrade technical-only reviews once visual checking is possible (not after a technical failure).
        missing_visual = can_see and rv and rv.get("visual") is None and not rv.get("visual_error") \
            and not any(i["severity"] == "major" for i in rv.get("technical", []))
        if never_checked or missing_visual:
            _review(d, store, j)


# ---------------------------------------------------------------- cost estimates (PRD §57)

RES_HEIGHT = {"480p": 480, "720p": 720, "1080p": 1080, "4k": 2160, "2160p": 2160}


def _fal_price(model: str) -> dict | None:
    key = os.environ.get("FAL_KEY")
    if not key:
        return None
    cache_path = os.path.join(CACHE_DIR, "fal_prices.json")
    cache = _read(cache_path, {})
    hit = cache.get(model)
    if hit and time.time() - hit["at"] < 86400:
        return hit["price"]
    r = requests.get("https://api.fal.ai/v1/models/pricing", params={"endpoint_id": model},
                     headers={**UA, "Authorization": f"Key {key}"}, timeout=30)
    price = next(iter(r.json().get("prices", [])), None) if r.ok else None
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache[model] = {"price": price, "at": int(time.time())}
    _write(cache_path, cache)
    return price


def estimate_payload(provider: str, model: str, man: dict, payload: dict) -> dict:
    """Best-effort USD estimate for one request. Returns {'usd': float|None, 'basis': str}."""
    if provider == "google":
        return {"usd": None, "basis": "Google bills per second of video / per image; see your Google AI Studio usage."}
    if provider != "fal":
        return {"usd": None, "basis": "Kie bills in credits; the exact amount is shown after each render."}
    price = _fal_price(model)
    if not price:
        return {"usd": None, "basis": "Price not published for this model."}
    roles = man["roles"]
    secs = float(str(payload.get(roles.get("duration", "duration"), 5)).rstrip("s") or 5)
    unit, unit_price = price.get("unit", ""), float(price.get("unit_price", 0))
    if "second" in unit:
        return {"usd": round(unit_price * secs, 3), "basis": f"${unit_price}/s × {secs:g}s"}
    if "minute" in unit:
        return {"usd": round(unit_price * secs / 60, 3), "basis": f"${unit_price}/min × {secs:g}s"}
    if "token" in unit:
        # ByteDance video tokens ≈ width × height × fps × seconds / 1024.
        h = RES_HEIGHT.get(str(payload.get(roles.get("resolution", "resolution"), "720p")).lower(), 720)
        m = re.match(r"^(\d+):(\d+)$", str(payload.get(roles.get("aspect_ratio", "aspect_ratio"), "16:9")))
        ar = int(m.group(1)) / int(m.group(2)) if m else 16 / 9
        w_px, h_px = (h * ar, h) if ar >= 1 else (h, h / ar)
        tokens = w_px * h_px * 24 * secs / 1024
        per = 1000 if "1000" in unit else 1_000_000 if "million" in unit.lower() else 1
        return {"usd": round(tokens / per * unit_price, 3), "basis": f"≈{tokens / 1000:.0f}k tokens × ${unit_price}/{per:,} tokens"}
    if any(u in unit for u in ("video", "request", "generation", "image")):
        return {"usd": round(unit_price, 3), "basis": f"${unit_price} per {unit}"}
    return {"usd": None, "basis": f"Billed per {unit}."}


def estimate(d: str, shot_ids: list[str], provider: str, model: str | None, kind: str = "video") -> dict:
    project = _read(os.path.join(d, "project.json"), {})
    _, plan = _load_plan(d)
    man = manifest(provider, model or (AUTO_IMAGE if kind == "image" else AUTO)[provider])
    total, per, unknown = 0.0, [], 0
    refs = [{"label": r["label"], "url": "x"} for r in _reference_files(d, project, None)]
    lip_prov = _lipsync_provider() if kind == "video" else None
    lip_shots = 0
    for sid in shot_ids:
        shot, scene = _shot(plan, sid)
        payload = compile_request(shot, scene, plan, project, man, refs)
        e = estimate_payload(provider, man["model"], man, payload)
        if lip_prov and wants_lipsync_pass(d, project, plan, shot):
            lip_shots += 1
            lman = manifest(lip_prov, AUTO_LIPSYNC[lip_prov])
            secs = payload.get(man["roles"].get("duration", "duration"), 5)
            le = estimate_payload(lip_prov, lman["model"], {**lman, "roles": {**lman["roles"], "duration": "duration"}}, {"duration": secs})
            if e["usd"] is not None and le["usd"] is not None:
                e = {**e, "usd": round(e["usd"] + le["usd"], 3)}
        per.append({"shot_id": sid, **e})
        if e["usd"] is None:
            unknown += 1
        else:
            total += e["usd"]
    out = {"provider": provider, "model": man["model"], "shots": len(shot_ids), "usd": round(total, 2) if not unknown else None,
           "usd_known": round(total, 2), "unknown": unknown, "basis": per[0]["basis"] if per else "",
           "lipsync_shots": lip_shots}
    if provider == "kie" and os.environ.get("KIE_KEY"):
        try:
            r = requests.get("https://api.kie.ai/api/v1/chat/credit", headers={**UA, "Authorization": f"Bearer {os.environ['KIE_KEY']}"}, timeout=20)
            out["kie_credits"] = r.json().get("data")
        except requests.RequestException:
            pass
    return out


def resolve(d: str, job_id: str, action: str) -> dict:
    store = Store(d)
    j = next((x for x in store.jobs if x["id"] == job_id), None)
    if not j:
        raise SystemExit("That render job no longer exists.")
    if action == "retry" and j["state"] in ("failed", "uncertain"):
        store.update(j, state="queued", error=None, provider_job_id=None)
    elif action == "dismiss" and j["state"] not in ACTIVE:
        store.update(j, state="dismissed")
    elif action == "accept" and j["state"] == "ready":
        store.update(j, review={**(j.get("review") or {}), "accepted": True})
    else:
        raise SystemExit(f"Can't {action} a job that is {j['state']}.")
    return j


def preview(d: str, shot_id: str, provider: str, model: str | None, overrides: dict | None, kind: str = "video") -> dict:
    """Show exactly what would be sent (reference URLs shown as local files). Costs nothing."""
    project = _read(os.path.join(d, "project.json"), {})
    _, plan = _load_plan(d)
    shot, scene = _shot(plan, shot_id)
    man = manifest(provider, model or (AUTO_IMAGE if kind == "image" else AUTO)[provider])
    refs = [{"label": r["label"], "url": f"(upload) {os.path.basename(r['path'])}"} for r in _reference_files(d, project, shot)
            if kind != "image" or not r["label"].startswith("set and props")]
    plan_name = "directed" if os.path.exists(os.path.join(d, "directed.json")) else "production"
    kf = approved_keyframe(d, plan_name, shot_id) if kind == "video" else None
    refs = _with_keyframe(refs, kf)
    sung = _sung_for(d, shot, plan, man) if kind == "video" else None
    return {"manifest": man, "payload": compile_request(shot, scene, plan, project, man, refs, overrides, None, sung),
            "keyframe": kf,
            "lip_sync": bool(sung), "singing": singing(d, shot, plan)}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="pulseframe-render")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("catalog"); c.add_argument("--provider", required=True); c.add_argument("--kind", default="video")
    m = sub.add_parser("manifest"); m.add_argument("--provider", required=True); m.add_argument("--model", required=True)
    m.add_argument("--refresh", action="store_true")
    for name in ("preview", "enqueue"):
        s = sub.add_parser(name)
        s.add_argument("project"); s.add_argument("--shots", required=True); s.add_argument("--provider", required=True)
        s.add_argument("--model"); s.add_argument("--overrides", default="{}"); s.add_argument("--fix-notes", default="[]")
        s.add_argument("--kind", default="video", choices=["video", "image", "lipsync"]); s.add_argument("--source-job")
    r = sub.add_parser("run"); r.add_argument("project")
    es = sub.add_parser("estimate"); es.add_argument("project"); es.add_argument("--shots", required=True)
    es.add_argument("--provider", required=True); es.add_argument("--model"); es.add_argument("--kind", default="video")
    rs = sub.add_parser("resolve"); rs.add_argument("project"); rs.add_argument("--job", required=True)
    rs.add_argument("--action", choices=["retry", "dismiss", "accept"], required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "catalog":
            emit(event="result", data=catalog(a.provider, a.kind))
        elif a.cmd == "manifest":
            emit(event="result", data=manifest(a.provider, a.model, a.refresh))
        elif a.cmd == "preview":
            emit(event="result", data=preview(a.project, a.shots.split(",")[0], a.provider, a.model, json.loads(a.overrides), a.kind))
        elif a.cmd == "enqueue":
            emit(event="result", data=enqueue(a.project, a.shots.split(","), a.provider, a.model, json.loads(a.overrides),
                                              json.loads(a.fix_notes), a.kind, a.source_job))
        elif a.cmd == "run":
            run(a.project)
        elif a.cmd == "estimate":
            emit(event="result", data=estimate(a.project, a.shots.split(","), a.provider, a.model, a.kind))
        elif a.cmd == "resolve":
            emit(event="result", data=resolve(a.project, a.job, a.action))
    except SystemExit as e:
        emit(event="error", message=str(e))
        return 1
    except Exception as e:  # readable failure for the app
        emit(event="error", message=f"{type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
