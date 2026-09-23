import { useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { api, errorText } from "./api";
import { Close, Note, Script } from "./icons";

const baseName = (p: string) => p.split(/[\\/]/).pop()!.replace(/\.[^.]+$/, "");

/** Song → lyrics → optional script. Everything else is decided later (Simple Mode). */
export function NewProject({ songPath, onCancel, onCreated }: {
  songPath: string; onCancel: () => void; onCreated: (dir: string) => void;
}) {
  const [title, setTitle] = useState(baseName(songPath).replace(/[-_]+/g, " ").trim());
  const [lyrics, setLyrics] = useState("");
  const [script, setScript] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const loadLyrics = async () => {
    const f = await open({ filters: [{ name: "Lyrics", extensions: ["txt", "lrc"] }] });
    if (typeof f === "string") setLyrics(await api.readText(f));
  };
  const chooseScript = async () => {
    const f = await open({ filters: [{ name: "Script", extensions: ["pdf", "txt", "md"] }] });
    if (typeof f === "string") setScript(f);
  };
  const create = async () => {
    setBusy(true); setError("");
    try {
      onCreated(await api.createProject(songPath, title.trim() || "Untitled", lyrics || null, script));
    } catch (e) { setError(errorText(e)); setBusy(false); }
  };

  return (
    <div className="overlay">
      <div className="sheet glass" role="dialog" aria-label="New music video">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
          <div>
            <h2>New music video</h2>
            <p className="sub">Add what you have. PULSEFRAME handles the rest.</p>
          </div>
          <button className="icon-btn" onClick={onCancel} aria-label="Cancel"><Close /></button>
        </div>

        <div className="field">
          <label>Song</label>
          <div className="file-row"><span style={{ color: "var(--gold)" }}><Note /></span><span className="name">{songPath}</span></div>
        </div>
        <div className="field">
          <label htmlFor="title">Title</label>
          <input id="title" className="text-input" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="lyrics">Lyrics <span className="opt">Optional · use [Verse], [Chorus] tags for the best song map</span></label>
          <textarea id="lyrics" className="text-input" placeholder={"[Verse 1]\nPaste your lyrics here…"}
                    value={lyrics} onChange={(e) => setLyrics(e.target.value)} />
          <button className="btn ghost" style={{ marginTop: 6 }} onClick={loadLyrics}>Load from file</button>
        </div>
        <div className="field">
          <label>Script <span className="opt">Optional · scenes and shots you've already written</span></label>
          {script ? (
            <div className="file-row"><Script /><span className="name">{script}</span>
              <button className="btn ghost" onClick={() => setScript(null)}>Remove</button></div>
          ) : <button className="btn" onClick={chooseScript}><Script size={18} /> Add script</button>}
        </div>

        {error && <div className="error-text">{error}</div>}
        <div className="sheet-actions">
          <button className="btn ghost" onClick={onCancel}>Cancel</button>
          <button className="btn primary" onClick={create} disabled={busy}>{busy ? "Creating…" : "Listen to the song"}</button>
        </div>
      </div>
    </div>
  );
}
