"""Export: assemble rendered takes on the song's timeline into one finished video (PRD §31, §71 EXPORT).

The master song is the clock. Every shot occupies exactly [start, end) of the song, converted to
whole frames from absolute times (not by summing durations), so cuts never drift off the beat.
Each take is trimmed from its head to the shot length and crop-filled to the preset frame. Shots
without a finished take become storyboard slates, so a draft cut can be exported at any time.
The song is muxed untouched (re-encoded once to AAC) and the video is cut to the song's length.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import textwrap

FPS = 24
PRESETS = {
    "youtube": {"label": "YouTube 16:9", "w": 1920, "h": 1080},
    "vertical": {"label": "TikTok / Reels 9:16", "w": 1080, "h": 1920},
    "square": {"label": "Square 1:1", "w": 1080, "h": 1080},
    "cinema": {"label": "Cinema 2.39:1", "w": 1920, "h": 804},
}
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def emit(**kw) -> None:
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list[str]) -> None:
    p = subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "ffmpeg failed")


def _read(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def slate(path: str, w: int, h: int, shot: dict, scene: dict | None) -> None:
    """Storyboard card for a shot that has no finished take yet."""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (w, h), (12, 15, 20))
    d = ImageDraw.Draw(im)

    def font(size, bold=False):
        for name in (("segoeuib.ttf" if bold else "segoeui.ttf"), "arial.ttf", "DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    u = min(w, h) / 1080
    pad = int(90 * u)
    y = int(h * 0.30)
    d.text((pad, pad), shot["id"], font=font(int(34 * u), True), fill=(138, 201, 255))
    if scene:
        d.text((pad, y), scene["heading"].upper(), font=font(int(26 * u)), fill=(104, 114, 129))
        y += int(56 * u)
    text = shot.get("visual_prompt") or " ".join(shot.get("beats", [])) or shot.get("description", "")
    chars = max(20, int((w - 2 * pad) / (22 * u)))
    for line in textwrap.wrap(text, chars)[:8]:
        d.text((pad, y), line, font=font(int(40 * u)), fill=(244, 247, 250))
        y += int(56 * u)
    d.text((pad, h - pad - int(30 * u)), "Not rendered yet", font=font(int(26 * u)), fill=(232, 180, 92))
    im.save(path)


def build(d: str, preset_key: str) -> dict:
    preset = PRESETS[preset_key]
    w, h = preset["w"], preset["h"]
    project = _read(os.path.join(d, "project.json"), {})
    song_map = _read(os.path.join(d, "songmap.json"))
    plan_name = "directed" if os.path.exists(os.path.join(d, "directed.json")) else "production"
    plan = _read(os.path.join(d, f"{plan_name}.json"))
    if not song_map or not plan:
        raise SystemExit("This project needs a song map and a shot plan before it can be exported.")
    jobs = _read(os.path.join(d, "jobs.json"), {"jobs": []})["jobs"]
    takes: dict[str, dict] = {}
    for j in jobs:  # latest finished take per shot of the current plan
        if j["plan"] == plan_name and j["state"] == "ready" and j.get("output"):
            if j["shot_id"] not in takes or j["created"] >= takes[j["shot_id"]]["created"]:
                takes[j["shot_id"]] = j

    duration = song_map["duration"]
    total_frames = round(duration * FPS)
    shots = sorted(((sh, sc) for sc in plan["scenes"] for sh in sc["shots"]), key=lambda x: x[0]["start"])
    work = os.path.join(d, "cache", "export", preset_key)
    os.makedirs(work, exist_ok=True)

    # Timeline of segments in whole frames; gaps (if any) are filled with black.
    segments, cursor = [], 0
    for sh, sc in shots:
        f0, f1 = max(cursor, round(sh["start"] * FPS)), min(total_frames, round(sh["end"] * FPS))
        if f0 > cursor:
            segments.append(("gap", None, None, f0 - cursor))
        if f1 > f0:
            segments.append(("shot", sh, sc, f1 - f0))
        cursor = max(cursor, f1)
    if cursor < total_frames:
        segments.append(("gap", None, None, total_frames - cursor))

    vf_fill = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={FPS},format=yuv420p")
    enc = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-an"]
    parts, rendered = [], 0
    for i, (kind, sh, sc, frames) in enumerate(segments):
        emit(event="progress", stage="assembling", progress=round(i / max(1, len(segments)) * 0.9, 3),
             detail=sh["id"] if sh else "gap")
        take = takes.get(sh["id"]) if sh else None
        src = os.path.join(d, take["output"]) if take else None
        if src and not os.path.exists(src):
            src = None
        key = hashlib.sha1(json.dumps([kind, sh and sh["id"], src, src and os.path.getmtime(src), frames, w, h,
                                       sh and (sh.get("visual_prompt") or sh.get("beats"))], default=str).encode()).hexdigest()[:12]
        out = os.path.join(work, f"{i:04d}_{key}.mp4")
        if not os.path.exists(out):
            if src:
                _run(["-i", src, "-vf", vf_fill, "-frames:v", str(frames), *enc, out + ".tmp.mp4"])
            else:
                img = out + ".png"
                if sh:
                    slate(img, w, h, sh, sc)
                else:
                    from PIL import Image
                    Image.new("RGB", (w, h), (0, 0, 0)).save(img)
                _run(["-loop", "1", "-framerate", str(FPS), "-i", img, "-vf", f"setsar=1,format=yuv420p",
                      "-frames:v", str(frames), *enc, out + ".tmp.mp4"])
                os.remove(img)
            _check_frames(out + ".tmp.mp4", frames)
            os.replace(out + ".tmp.mp4", out)
        rendered += 1 if src else 0
        parts.append(out)

    emit(event="progress", stage="adding the song", progress=0.93)
    listfile = os.path.join(work, "concat.txt")
    with open(listfile, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p.replace(os.sep, '/')}'\n")
    title = "".join(c for c in project.get("title", "PULSEFRAME") if c.isalnum() or c in " -_").strip() or "PULSEFRAME"
    stamp = time.strftime("%Y-%m-%d %H%M")
    status = "" if rendered == sum(1 for s in segments if s[0] == "shot") else " (draft)"
    out_path = os.path.join(d, "exports", f"{title} - {preset['label'].split(' ')[0]} - {stamp}{status}.mp4")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    song = os.path.join(d, project.get("song", "song.wav"))
    _run(["-f", "concat", "-safe", "0", "-i", listfile, "-i", song,
          "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "320k",
          "-t", f"{duration:.3f}", "-movflags", "+faststart", out_path + ".part.mp4"])
    os.replace(out_path + ".part.mp4", out_path)
    emit(event="progress", stage="done", progress=1.0)
    shot_count = sum(1 for s in segments if s[0] == "shot")
    return {"path": out_path, "preset": preset["label"], "width": w, "height": h, "fps": FPS,
            "duration": duration, "shots": shot_count, "rendered": rendered, "draft": rendered < shot_count}


def _check_frames(path: str, want: int) -> None:
    """Guard against off-by-one-frame drift, which would accumulate into lost sync."""
    p = subprocess.run([ffmpeg(), "-hide_banner", "-i", path, "-map", "0:v:0", "-c", "copy", "-f", "null", "-"],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    import re
    m = re.findall(r"frame=\s*(\d+)", p.stderr)
    got = int(m[-1]) if m else want
    if got != want:
        raise RuntimeError(f"Segment has {got} frames, expected {want}.")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="pulseframe-export")
    p.add_argument("project")
    p.add_argument("--preset", choices=list(PRESETS), default="youtube")
    a = p.parse_args(argv)
    try:
        emit(event="result", data=build(a.project, a.preset))
    except SystemExit as e:
        emit(event="error", message=str(e))
        return 1
    except Exception as e:
        emit(event="error", message=f"{type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
