import { useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { api, errorText, type ManifestInput } from "./api";
import * as I from "./icons";

export type MediaKind = "image" | "video" | "audio";
const EXT: Record<MediaKind, string[]> = {
  image: ["png", "jpg", "jpeg", "webp"],
  video: ["mp4", "mov", "webm", "m4v"],
  audio: ["mp3", "wav", "m4a", "aac", "flac"],
};

/** Which model inputs take media, judged from their name and description. */
export function mediaKind(f: ManifestInput): MediaKind | null {
  const isText = f.type === "string" || (f.type === "array" && (f.items ?? "string") === "string");
  if (!isText || f.enum?.length) return null;
  const n = `${f.name} ${f.description}`.toLowerCase();
  if (!/url|uri|image|video|audio|frame|reference|mask|file/.test(f.name.toLowerCase())) return null;
  if (/audio|voice|speech|sound|music/.test(n)) return "audio";
  if (/video/.test(f.name.toLowerCase())) return "video";
  return "image";
}

const isProject = (v: string) => v.startsWith("project:");
const label = (v: string) => (isProject(v) ? v.split("/").pop()! : v.startsWith("(upload) ") ? v.slice(9) : v.replace(/^https?:\/\//, "").slice(0, 38) + "…");

/** Upload-first media input: files are copied into the project and sent to the provider at render time. */
export function MediaInput({ dir, kind, multiple, value, max, onChange }: {
  dir: string; kind: MediaKind; multiple: boolean; value: unknown; max?: number | null; onChange: (v: unknown) => void;
}) {
  const items = (Array.isArray(value) ? value : value ? [value] : []).map(String);
  const [link, setLink] = useState("");
  const [error, setError] = useState("");
  const full = !!max && items.length >= max;

  const set = (list: string[]) => onChange(multiple ? list : list[list.length - 1] ?? null);
  const add = async () => {
    setError("");
    const picked = await open({ multiple, filters: [{ name: kind[0].toUpperCase() + kind.slice(1), extensions: EXT[kind] }] });
    const paths = picked === null ? [] : Array.isArray(picked) ? picked : [picked];
    try {
      const refs = [];
      for (const p of paths) refs.push((await api.importReference(dir, p)).ref);
      if (refs.length) set([...(multiple ? items : []), ...refs].slice(0, max ?? undefined));
    } catch (e) { setError(errorText(e)); }
  };

  return (
    <div className="media-input">
      <div className="media-list">
        {items.map((v, i) => (
          <div key={v + i} className="media-chip" title={v}>
            {isProject(v) && kind === "image" && <img src={api.mediaUrl(`${dir}/${v.slice(8)}`)} alt="" />}
            {isProject(v) && kind === "video" && <video src={api.mediaUrl(`${dir}/${v.slice(8)}`)} muted />}
            {kind === "audio" && <span className="media-ic"><I.Note size={14} /></span>}
            {multiple && kind !== "audio" && <span className="media-tag">@{kind === "image" ? "Image" : "Video"}{i + 1}</span>}
            <span className="media-name">{label(v)}</span>
            <button className="link" onClick={() => set(items.filter((_, k) => k !== i))} aria-label="Remove">✕</button>
          </div>
        ))}
      </div>
      <div className="media-actions">
        <button className="btn small" onClick={add} disabled={full}>{kind === "audio" ? (multiple ? "Add audio files…" : "Add audio file…") : `Add ${kind}${multiple ? "s" : ""}…`}</button>
        <input className="text-input" placeholder="or paste a link" value={link} onChange={(e) => setLink(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter" && /^https?:\/\//.test(link)) { set([...(multiple ? items : []), link]); setLink(""); } }} />
      </div>
      {max ? <div className="mi-desc">{items.length} of {max}</div> : null}
      {error && <div className="error-text">{error}</div>}
    </div>
  );
}
