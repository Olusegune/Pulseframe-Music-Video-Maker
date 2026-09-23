import { useEffect, useState } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { open } from "@tauri-apps/plugin-dialog";
import { api, type ProjectSummary } from "./api";
import { Gear, Mark, Note } from "./icons";

const AUDIO = ["mp3", "wav", "m4a"];

export function Home({ onSong, onOpen, onSettings }: {
  onSong: (path: string) => void; onOpen: (dir: string) => void; onSettings: () => void;
}) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [over, setOver] = useState(false);
  const [hint, setHint] = useState("");

  useEffect(() => { api.listProjects().then(setProjects).catch(() => setProjects([])); }, []);

  useEffect(() => {
    const un = getCurrentWebview().onDragDropEvent((e) => {
      const p = e.payload;
      if (p.type === "enter" || p.type === "over") setOver(true);
      else if (p.type === "leave") setOver(false);
      else if (p.type === "drop") {
        setOver(false);
        const song = p.paths.find((f) => AUDIO.includes(f.split(".").pop()!.toLowerCase()));
        if (song) onSong(song);
        else setHint("PULSEFRAME accepts MP3, WAV or M4A songs.");
      }
    });
    return () => { un.then((f) => f()); };
  }, [onSong]);

  const choose = async () => {
    const f = await open({ multiple: false, filters: [{ name: "Music", extensions: AUDIO }] });
    if (typeof f === "string") onSong(f);
  };
  const openExisting = async () => {
    const f = await open({ directory: true });
    if (typeof f === "string") onOpen(f);
  };

  return (
    <div className="home">
      <div className="home-top">
        <div className="wordmark"><Mark size={24} /> PULSEFRAME</div>
        <button className="icon-btn" onClick={onSettings} title="Settings" aria-label="Settings"><Gear /></button>
      </div>

      <div className="home-hero">
        <h1>DIRECT MUSIC<br />INTO MOTION</h1>
        <div className={`dropcard ${over ? "over" : ""}`}>
          <div className="note-icon"><Note size={34} /></div>
          <div className="big">Drop a song here</div>
          <button className="btn primary" onClick={choose}>Choose Music</button>
          <div className="hint">{hint || "MP3, WAV or M4A"}</div>
        </div>
        <button className="btn ghost" onClick={openExisting}>Open Project</button>
      </div>

      {projects.length > 0 && (
        <div className="recent">
          <h2>Recent</h2>
          <div className="recent-row">
            {projects.map((p) => (
              <button key={p.dir} className="project-card" onClick={() => onOpen(p.dir)}>
                <div className="t">{p.title}</div>
                <div className="m">{stateLabel(p.state)} · {new Date(p.modified * 1000).toLocaleDateString()}</div>
                <div className="mini-wave">{Array.from({ length: 36 }, (_, i) =>
                  <i key={i} style={{ height: `${25 + 70 * Math.abs(Math.sin(i * 1.7 + p.title.length))}%` }} />)}</div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export const stateLabel = (s: string) =>
  ({ new: "New", analyzing: "Listening…", analyzed: "Ready to direct", directed: "Directed" } as Record<string, string>)[s] ?? s;
