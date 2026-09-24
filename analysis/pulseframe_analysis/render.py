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
            "max_items": raw.get("maxItems"), "description": (raw.get("description") or "").strip(),
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


def manifest(provider: str, model: str, refresh: bool = False) -> dict:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{provider}__{re.sub(r'[^A-Za-z0-9._-]+', '_', model)}.json")
    if not refresh and os.path.exists(path) and time.time() - os.path.getmtime(path) < 7 * 86400:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    m = fal_manifest(model) if provider == "fal" else kie_manifest(model)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1, ensure_ascii=False)
    return m


def catalog(provider: str) -> list[dict]:
    """Video models a user can pick in Director Mode."""
    if provider == "fal":
        out, seen = [], set()
        for cat in ("image-to-video", "text-to-video", "video-to-video"):
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
        return out
    return [{"provider": "kie", "model": _slug_from_doc(e["doc"]), "category": e["kind"], "title": f"{e['family']} · {e['title']}",
             "doc": e["doc"]} for e in _kie_index() if e["kind"] == "video"]


def _slug_from_doc(doc: str) -> str:
    # docs.kie.ai/market/bytedance/seedance-2.md -> bytedance/seedance-2 (matches Kie ids for most models;
    # the manifest fetch reads the exact id from the doc's schema).
    return doc.split("/market/")[1].removesuffix(".md")


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


def compile_request(shot: dict, scene: dict | None, plan: dict, project: dict, man: dict,
                    refs: list[dict], overrides: dict | None = None) -> dict:
    """refs: [{'label': 'Sege, Amara, Young Sege — character sheet', 'url': ...}] already uploaded."""
    roles, fields = man["roles"], {f["name"]: f for f in man["inputs"]}
    payload: dict = {}
    style = plan.get("meta", {}).get("VISUAL STYLE", "")
    body = shot.get("visual_prompt") or " ".join(shot.get("beats", [])) or shot.get("description", "")
    parts = [body]
    if shot.get("framing"):
        parts.append(f"Shot: {shot['framing']}" + (f", {shot.get('camera_movement') or ', '.join(shot.get('camera_moves', []))}"
                                                   if shot.get("camera_movement") or shot.get("camera_moves") else "") + ".")
    if shot.get("lighting"):
        parts.append(f"Lighting: {shot['lighting']}")
    if style:
        parts.append(f"Style: {style}")
    image_refs = refs[: fields[roles["ref_images"]].get("max_items") or len(refs)] if "ref_images" in roles else []
    if image_refs:
        ordinal = ["first", "second", "third", "fourth", "fifth", "sixth"]
        tags = [f"{man['ref_syntax'].format(n=i + 1)} is the {r['label']}" if man.get("ref_syntax")
                else f"the {ordinal[min(i, 5)]} reference image is the {r['label']}" for i, r in enumerate(image_refs)]
        parts.append("References: " + "; ".join(tags) + ". Match the characters' faces, hair and wardrobe exactly.")
    parts.append("No on-screen text, no subtitles, no watermark. Performers do not lip-sync.")
    payload[roles.get("prompt", "prompt")] = " ".join(p.strip() for p in parts if p)

    if image_refs:
        f = fields[roles["ref_images"]]
        urls = [r["url"] for r in image_refs]
        payload[f["name"]] = urls if f["type"] == "array" else urls[0]
    elif refs and "first_frame" in roles:
        payload[roles["first_frame"]] = refs[0]["url"]
    if "duration" in roles:
        payload[roles["duration"]] = _duration_value(fields[roles["duration"]], shot["end"] - shot["start"])
    if "aspect_ratio" in roles:
        ar = project.get("aspect_ratio", "16:9")
        m = re.match(r"^([\d.]+):([\d.]+)$", ar)
        pick = _nearest_aspect(fields[roles["aspect_ratio"]].get("enum"), float(m.group(1)) / float(m.group(2)) if m else 16 / 9)
        if pick:
            payload[roles["aspect_ratio"]] = pick
    if "resolution" in roles:
        opts = fields[roles["resolution"]].get("enum") or []
        payload[roles["resolution"]] = "720p" if "720p" in opts else fields[roles["resolution"]].get("default") or (opts[0] if opts else None)
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


PROVIDERS = {"fal": Fal, "kie": Kie}


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


def _reference_files(d: str, project: dict) -> list[dict]:
    refs = project.get("references") or {}
    out = []
    if refs.get("characters") and os.path.exists(os.path.join(d, refs["characters"])):
        out.append({"label": "character sheet (Sege, Amara, Young Sege: faces, turnarounds, outfits)",
                    "path": os.path.join(d, refs["characters"])})
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


def enqueue(d: str, shot_ids: list[str], provider: str, model: str | None, overrides: dict | None) -> list[dict]:
    project = _read(os.path.join(d, "project.json"), {})
    plan_name, plan = _load_plan(d)
    model = model or AUTO[provider]
    man = manifest(provider, model)
    store = Store(d)
    made = []
    for sid in shot_ids:
        if any(j["shot_id"] == sid and j["plan"] == plan_name and j["state"] in ACTIVE for j in store.jobs):
            continue  # never double-queue a shot that is already rendering
        shot, scene = _shot(plan, sid)
        job = {"id": uuid.uuid4().hex[:12], "shot_id": sid, "plan": plan_name, "source_shots": shot.get("source_shots", []),
               "shot_start": shot["start"], "shot_end": shot["end"], "provider": provider, "model": man["model"],
               "overrides": overrides or {}, "state": "queued", "provider_job_id": None, "attempts": 0,
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
    emit(event="progress", stage="all renders settled")


def _submit(d: str, store: Store, project: dict, p, j: dict) -> None:
    _, plan = _load_plan(d) if j["plan"] == "directed" else ("production", _read(os.path.join(d, "production.json"), {}))
    shot, scene = _shot(plan, j["shot_id"])
    man = manifest(j["provider"], j["model"])
    emit(event="progress", stage=f"preparing {j['shot_id']}")
    refs = _uploaded(d, p, _reference_files(d, project))
    payload = compile_request(shot, scene, plan, project, man, refs, j.get("overrides"))
    # Persist intent BEFORE the billable call; the id is persisted the moment it returns.
    store.update(j, state="submitting", payload=payload, attempts=j["attempts"] + 1)
    emit(event="progress", stage=f"sending {j['shot_id']} to {j['provider']}")
    sub = p.submit(j["model"], payload)
    store.update(j, state="submitted", provider_job_id=sub.pop("id"), provider_meta=sub, submitted=int(time.time()))


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
    out = os.path.join(out_dir, f"{j['shot_id']}__{j['id']}.mp4")
    emit(event="progress", stage=f"downloading {j['shot_id']}")
    with requests.get(res["url"], stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(out + ".part", "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    os.replace(out + ".part", out)
    store.update(j, state="ready", output=os.path.relpath(out, d).replace(os.sep, "/"), output_url=res["url"],
                 cost=res.get("cost"), cost_unit=res.get("cost_unit"), finished=int(time.time()))


def resolve(d: str, job_id: str, action: str) -> dict:
    store = Store(d)
    j = next((x for x in store.jobs if x["id"] == job_id), None)
    if not j:
        raise SystemExit("That render job no longer exists.")
    if action == "retry" and j["state"] in ("failed", "uncertain"):
        store.update(j, state="queued", error=None, provider_job_id=None)
    elif action == "dismiss" and j["state"] not in ACTIVE:
        store.update(j, state="dismissed")
    else:
        raise SystemExit(f"Can't {action} a job that is {j['state']}.")
    return j


def preview(d: str, shot_id: str, provider: str, model: str | None, overrides: dict | None) -> dict:
    """Show exactly what would be sent (reference URLs shown as local files). Costs nothing."""
    project = _read(os.path.join(d, "project.json"), {})
    _, plan = _load_plan(d)
    shot, scene = _shot(plan, shot_id)
    man = manifest(provider, model or AUTO[provider])
    refs = [{"label": r["label"], "url": f"(upload) {os.path.basename(r['path'])}"} for r in _reference_files(d, project)]
    return {"manifest": man, "payload": compile_request(shot, scene, plan, project, man, refs, overrides)}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="pulseframe-render")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("catalog"); c.add_argument("--provider", required=True)
    m = sub.add_parser("manifest"); m.add_argument("--provider", required=True); m.add_argument("--model", required=True)
    m.add_argument("--refresh", action="store_true")
    for name in ("preview", "enqueue"):
        s = sub.add_parser(name)
        s.add_argument("project"); s.add_argument("--shots", required=True); s.add_argument("--provider", required=True)
        s.add_argument("--model"); s.add_argument("--overrides", default="{}")
    r = sub.add_parser("run"); r.add_argument("project")
    rs = sub.add_parser("resolve"); rs.add_argument("project"); rs.add_argument("--job", required=True)
    rs.add_argument("--action", choices=["retry", "dismiss"], required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "catalog":
            emit(event="result", data=catalog(a.provider))
        elif a.cmd == "manifest":
            emit(event="result", data=manifest(a.provider, a.model, a.refresh))
        elif a.cmd == "preview":
            emit(event="result", data=preview(a.project, a.shots.split(",")[0], a.provider, a.model, json.loads(a.overrides)))
        elif a.cmd == "enqueue":
            emit(event="result", data=enqueue(a.project, a.shots.split(","), a.provider, a.model, json.loads(a.overrides)))
        elif a.cmd == "run":
            run(a.project)
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
