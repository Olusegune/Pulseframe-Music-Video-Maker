import { useEffect, useRef, useState } from "react";
import { api, errorText, type EngineEvent } from "./api";
import * as I from "./icons";

const EXAMPLES = [
  "Make the second chorus much more energetic",
  "Less movement during Verse 1",
  "Make the selected shot more intimate",
  "Keep the performance but make the camera calmer in the bridge",
  "Warmer, golden light for the final chorus",
];

export type CommandResult = { id: string | null; summary: string; not_done: string; changed: string[] };

/** PRD §26: a temporary command surface, not a chat. Ctrl+K opens it; Esc closes it. */
export function DirectorCommand({ dir, selected, playhead, onApplied, onClose, onSettings }: {
  dir: string; selected: string | null; playhead: number;
  onApplied: (r: CommandResult) => void; onClose: () => void; onSettings: () => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { input.current?.focus(); }, []);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", k);
    const un = api.onEngine((e: EngineEvent) => { if (e.task === "command" && e.stage) setBusy(e.stage.charAt(0).toUpperCase() + e.stage.slice(1) + "…"); });
    return () => { window.removeEventListener("keydown", k); un.then((f) => f()); };
  }, [busy, onClose]);

  const run = async (text: string) => {
    if (!text.trim()) return;
    const keys = await api.keyStatus();
    if (!keys.openai) { onClose(); onSettings(); return; }
    setError(""); setBusy("Reading your note…");
    try { onApplied(await api.directorCommand(dir, text.trim(), selected, playhead)); }
    catch (e) { setError(errorText(e)); setBusy(""); }
  };

  return (
    <div className="cmd-backdrop" onClick={() => !busy && onClose()}>
      <div className="cmd glass" role="dialog" aria-label="Director Command" onClick={(e) => e.stopPropagation()}>
        <div className="cmd-row">
          <span className="cmd-label">Direct</span>
          <input ref={input} className="cmd-input" value={note} disabled={!!busy} placeholder="Give a note, e.g. “less dancing in Verse 1”"
                 onChange={(e) => setNote(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run(note)} aria-label="Director note" />
          <kbd>Enter</kbd>
        </div>
        {busy ? <div className="cmd-busy"><span className="spin" /> {busy}</div> : (
          <div className="cmd-hints">
            {selected && <div className="dim">Selected: {selected}. Notes can say “this shot”.</div>}
            {EXAMPLES.map((x) => <button key={x} className="cmd-ex" onClick={() => { setNote(x); run(x); }}>{x}</button>)}
          </div>
        )}
        {error && <div className="error-text" style={{ padding: "0 16px 12px" }}>{error}</div>}
      </div>
    </div>
  );
}

/** What changed, with Undo. Shown briefly after a command. */
export function CommandToast({ result, onUndo, onDismiss, onSelect }: {
  result: CommandResult; onUndo: () => void; onDismiss: () => void; onSelect: (id: string) => void;
}) {
  return (
    <div className="toast glass cmd-toast" role="status">
      <div className="t">Directed</div>
      <div className="s">{result.summary}</div>
      {result.changed.length > 0 && <div className="cmd-changed">{result.changed.map((id) =>
        <button key={id} className="chip num" onClick={() => onSelect(id)}>{id}</button>)}</div>}
      {result.not_done && <div className="dim" style={{ marginTop: 6 }}>Not changed: {result.not_done}</div>}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 10 }}>
        {result.id && result.changed.length > 0 && <button className="btn small" onClick={onUndo}><I.SkipBack size={12} /> Undo</button>}
        <button className="btn small ghost" onClick={onDismiss}>OK</button>
      </div>
    </div>
  );
}
