import { useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { api, errorText, type LoadedProject } from "./api";
import * as I from "./icons";

export type References = { characters?: string; sets?: string; cast?: Record<string, string> };

type Item = { key: string; title: string; why: string; done: boolean; need: "required" | "recommended" | "optional"; detail?: string };

/** What PULSEFRAME can use, why it helps, and what's there. Shared by New Project and the Studio. */
export function materialItems(p: { song: boolean; lyrics: boolean; script: boolean; plan: boolean; refs: References; look: boolean }): Item[] {
  const cast = Object.keys(p.refs.cast ?? {});
  return [
    { key: "song", title: "Song", need: "required", done: p.song,
      why: "The master timeline. Every cut lands on its beats." },
    { key: "lyrics", title: "Lyrics with section tags", need: "recommended", done: p.lyrics,
      why: "Gives the real song structure ([Verse], [Chorus]…), times every line and drives lip-sync." },
    { key: "cast", title: "Character images", need: "recommended", done: cast.length > 0 || !!p.refs.characters,
      detail: cast.length ? cast.join(", ") : p.refs.characters ? "Combined character sheet" : undefined,
      why: "The biggest factor for the same faces, hair and outfits in every shot. Best: one image per character." },
    { key: "sets", title: "Locations & props", need: "optional", done: !!p.refs.sets,
      why: "Keeps places, props and colours consistent between shots." },
    { key: "story", title: "Script or story", need: "optional", done: p.script || p.plan,
      why: "Scenes and shots you've written are followed exactly. Without one, PULSEFRAME proposes three directions." },
    { key: "look", title: "Look", need: "optional", done: p.look,
      why: "One art or animation style for every shot. Auto matches your character images." },
  ];
}

export const TIPS = [
  "One character per image, face and full body, on a plain background.",
  "No text, labels, logos or collages in reference images: models copy them into the video.",
  "Name characters exactly as they're named in your script or lyrics.",
  "Tag lyrics with [Intro], [Verse 1], [Chorus], [Bridge]… on their own lines.",
];

export function MaterialsChecklist({ items, compact }: { items: Item[]; compact?: boolean }) {
  return (
    <ul className={`materials ${compact ? "compact" : ""}`}>
      {items.map((m) => (
        <li key={m.key} className={m.done ? "done" : ""}>
          <span className="mat-state">{m.done ? <I.Check size={14} /> : <I.Circle size={14} />}</span>
          <span className="mat-body">
            <span className="mat-title">{m.title} <span className={`mat-need ${m.need}`}>{m.need}</span></span>
            {m.detail && <span className="mat-detail">{m.detail}</span>}
            {!compact && <span className="mat-why">{m.why}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Pick character images (named) and a locations sheet. Used before the project exists (New Project). */
export type PendingRefs = { cast: { name: string; path: string }[]; sets: string | null };

export function ReferencePicker({ value, onChange }: { value: PendingRefs; onChange: (v: PendingRefs) => void }) {
  const [name, setName] = useState("");
  const pick = async () => {
    const f = await open({ filters: [{ name: "Image", extensions: ["png", "jpg", "jpeg", "webp"] }] });
    return typeof f === "string" ? f : null;
  };
  const addChar = async () => {
    const f = await pick();
    if (f) { onChange({ ...value, cast: [...value.cast, { name: name.trim() || `Character ${value.cast.length + 1}`, path: f }] }); setName(""); }
  };
  return (
    <div className="ref-picker">
      {value.cast.map((c, i) => (
        <div key={i} className="file-row"><I.Assets size={16} /><span className="name"><b>{c.name}</b> · {c.path.split(/[\\/]/).pop()}</span>
          <button className="btn ghost small" onClick={() => onChange({ ...value, cast: value.cast.filter((_, k) => k !== i) })}>Remove</button></div>
      ))}
      <div className="key-row">
        <input className="text-input" placeholder="Character name, e.g. Sege" value={name} onChange={(e) => setName(e.target.value)} />
        <button className="btn" onClick={addChar}>Add character image…</button>
      </div>
      {value.sets ? (
        <div className="file-row"><I.Assets size={16} /><span className="name">Locations & props · {value.sets.split(/[\\/]/).pop()}</span>
          <button className="btn ghost small" onClick={() => onChange({ ...value, sets: null })}>Remove</button></div>
      ) : <button className="btn ghost" onClick={async () => { const f = await pick(); if (f) onChange({ ...value, sets: f }); }}>Add locations & props image…</button>}
    </div>
  );
}

export async function savePendingRefs(dir: string, r: PendingRefs) {
  for (const c of r.cast) await api.addReference(dir, c.path, "cast", c.name);
  if (r.sets) await api.addReference(dir, r.sets, "sets", null);
}

/** Studio: the checklist plus add/remove for an existing project. */
export function MaterialsPanel({ project, hasPlan, onChanged }: { project: LoadedProject; hasPlan: boolean; onChanged: () => void }) {
  const [refs, setRefs] = useState<References>((project.project as { references?: References }).references ?? {});
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const look = project.project.look;
  const items = materialItems({ song: !!project.song_path, lyrics: !!project.project.lyrics, script: !!project.project.script,
    plan: hasPlan, refs, look: typeof look === "object" ? look.style !== "auto" : !!look });
  const missing = items.filter((m) => !m.done && m.need !== "optional").length;

  const add = async (role: "cast" | "sets" | "characters") => {
    setError("");
    const f = await open({ filters: [{ name: "Image", extensions: ["png", "jpg", "jpeg", "webp"] }] });
    if (typeof f !== "string") return;
    try { setRefs(await api.addReference(project.dir, f, role, role === "cast" ? (name.trim() || null) : null)); setName(""); onChanged(); }
    catch (e) { setError(errorText(e)); }
  };
  const remove = async (role: string, n?: string) => {
    try { setRefs(await api.removeReference(project.dir, role, n ?? null)); onChanged(); } catch (e) { setError(errorText(e)); }
  };

  return (
    <div className="insp-section">
      <h4>Materials {missing ? <span className="mat-need recommended">{missing} to add</span> : null}</h4>
      <MaterialsChecklist items={items} compact />
      <div className="ref-grid">
        {Object.entries(refs.cast ?? {}).map(([n, rel]) => (
          <div key={n} className="ref-tile" title={n}>
            <img src={api.mediaUrl(`${project.dir}/${rel}`)} alt={n} />
            <span>{n}</span><button className="link" onClick={() => remove("cast", n)}>Remove</button>
          </div>
        ))}
        {refs.sets && <div className="ref-tile"><img src={api.mediaUrl(`${project.dir}/${refs.sets}`)} alt="Locations" /><span>Locations</span>
          <button className="link" onClick={() => remove("sets")}>Remove</button></div>}
      </div>
      <div className="key-row" style={{ marginTop: 8 }}>
        <input className="text-input" placeholder="Character name" value={name} onChange={(e) => setName(e.target.value)} />
        <button className="btn small" onClick={() => add("cast")} disabled={!name.trim()}>Add image…</button>
      </div>
      {!refs.sets && <button className="btn ghost small" style={{ marginTop: 6 }} onClick={() => add("sets")}>Add locations & props image…</button>}
      <details className="mat-tips"><summary>Tips for best results</summary><ul>{TIPS.map((t) => <li key={t}>{t}</li>)}</ul></details>
      {error && <div className="error-text">{error}</div>}
    </div>
  );
}
