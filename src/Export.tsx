import { useEffect, useState } from "react";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { api, errorText, fmtTime, type ExportResult } from "./api";
import * as I from "./icons";

const PRESETS = [
  { id: "youtube", label: "YouTube", sub: "16:9 · 1920×1080", ar: 16 / 9 },
  { id: "vertical", label: "TikTok / Reels", sub: "9:16 · 1080×1920", ar: 9 / 16 },
  { id: "square", label: "Square", sub: "1:1 · 1080×1080", ar: 1 },
  { id: "cinema", label: "Cinema", sub: "2.39:1 · 1920×804", ar: 2.39 },
];

/** PRD §31: simple presets. The song is the clock; every cut lands on its frame. */
export function ExportSheet({ dir, projectAspect, shots, rendered, onClose }: {
  dir: string; projectAspect?: string; shots: number; rendered: number; onClose: () => void;
}) {
  const natural = projectAspect === "2.39:1" ? "cinema" : "youtube";
  const [preset, setPreset] = useState(natural);
  const [progress, setProgress] = useState<{ stage: string; p: number; detail?: string } | null>(null);
  const [result, setResult] = useState<ExportResult | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const un = api.onEngine((e) => {
      if (e.task === "export" && e.stage) setProgress({ stage: e.stage, p: (e.progress as number) ?? 0, detail: e.detail as string });
    });
    return () => { un.then((f) => f()); };
  }, []);

  const run = async () => {
    setError(""); setResult(null); setProgress({ stage: "starting", p: 0 });
    try { setResult(await api.exportProject(dir, preset)); } catch (e) { setError(errorText(e)); }
    finally { setProgress(null); }
  };

  const draft = rendered < shots;
  return (
    <div className="overlay" onClick={progress ? undefined : onClose}>
      <div className="sheet glass" role="dialog" aria-label="Export" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
          <div>
            <h2>Export</h2>
            <p className="sub">{rendered} of {shots} shots rendered.
              {draft ? " Shots without a take appear as storyboard cards, so this will be a draft cut." : " Ready for a final export."}</p>
          </div>
          {!progress && <button className="icon-btn" onClick={onClose} aria-label="Close"><I.Close /></button>}
        </div>

        <div className="preset-grid" role="radiogroup" aria-label="Format">
          {PRESETS.map((p) => (
            <button key={p.id} role="radio" aria-checked={preset === p.id} className={`preset ${preset === p.id ? "on" : ""}`}
                    onClick={() => setPreset(p.id)} disabled={!!progress}>
              <span className="frame" style={{ aspectRatio: String(p.ar) }} />
              <span className="pl">{p.label}{p.id === natural && <span className="rec"> · project</span>}</span>
              <span className="ps">{p.sub}</span>
            </button>
          ))}
        </div>
        {preset !== natural && <p className="dim" style={{ marginTop: 10 }}>Shots are framed for {projectAspect ?? "16:9"}; this format crops them to fill the frame.</p>}

        {progress && (
          <div style={{ marginTop: 18 }}>
            <div className="dim">{progress.stage === "assembling" ? `Assembling ${progress.detail ?? ""}` : cap(progress.stage)}</div>
            <div className="progress"><i style={{ width: `${Math.round(progress.p * 100)}%` }} /></div>
          </div>
        )}
        {result && (
          <div className="export-done">
            <div className="status-ok"><I.Check size={16} /> Exported {result.draft ? "draft " : ""}— {result.width}×{result.height}, {result.fps} fps, {fmtTime(result.duration)}</div>
            <div className="dim" style={{ wordBreak: "break-all", marginTop: 6 }}>{result.path}</div>
          </div>
        )}
        {error && <div className="error-text">{error}</div>}

        <div className="sheet-actions">
          {result && <button className="btn" onClick={() => revealItemInDir(result.path)}>Show in folder</button>}
          <button className="btn primary" onClick={run} disabled={!!progress}>{progress ? "Exporting…" : result ? "Export again" : "Export video"}</button>
        </div>
      </div>
    </div>
  );
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
