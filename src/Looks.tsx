import { useEffect, useMemo, useState } from "react";
import { api, type Look, type Style } from "./api";
import * as I from "./icons";

let cache: Style[] | null = null;
export function useStyles(): Style[] {
  const [styles, setStyles] = useState<Style[]>(cache ?? []);
  useEffect(() => { if (!cache) api.listStyles().then((s) => { cache = s; setStyles(s); }).catch(() => {}); }, []);
  return styles;
}

export const normalizeLook = (l: Look | string | undefined): Look =>
  !l ? { style: "auto" } : typeof l === "string" ? { style: "auto", notes: l } : l;

export function lookName(styles: Style[], look: Look) {
  return styles.find((s) => s.id === look.style)?.name ?? "Auto: match my references";
}

/** One visual choice for the whole video. Its wording is injected into every shot's render prompt. */
export function LookPicker({ value, director, onCancel, onSave }: {
  value: Look; director: boolean; onCancel: () => void; onSave: (l: Look) => void;
}) {
  const styles = useStyles();
  const [sel, setSel] = useState(value.style);
  const [notes, setNotes] = useState(value.notes ?? "");
  const [prompt, setPrompt] = useState(value.prompt ?? "");
  const [avoid, setAvoid] = useState(value.avoid ?? "");
  const [q, setQ] = useState("");
  const chosen = styles.find((s) => s.id === sel);

  const groups = useMemo(() => {
    const m = new Map<string, Style[]>();
    for (const s of styles) {
      if (q && !`${s.name} ${s.description} ${s.group}`.toLowerCase().includes(q.toLowerCase())) continue;
      m.set(s.group, [...(m.get(s.group) ?? []), s]);
    }
    return [...m.entries()];
  }, [styles, q]);

  const pick = (id: string) => { setSel(id); if (id !== value.style) { setPrompt(""); setAvoid(""); } };
  const save = () => onSave({
    style: sel, ...(notes.trim() && { notes: notes.trim() }),
    ...(director && prompt.trim() && { prompt: prompt.trim() }), ...(director && avoid.trim() && { avoid: avoid.trim() }),
  });

  return (
    <div className="overlay" onClick={onCancel}>
      <div className="sheet glass look-sheet" role="dialog" aria-label="Choose a look" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: 12 }}>
          <div>
            <h2>Look</h2>
            <p className="sub">One style for the whole video. PULSEFRAME applies it to every shot automatically.</p>
          </div>
          <button className="icon-btn" onClick={onCancel} aria-label="Close"><I.Close /></button>
        </div>
        <input className="text-input" placeholder="Search looks" value={q} onChange={(e) => setQ(e.target.value)} style={{ marginBottom: 14 }} />
        <div className="look-scroll">
          {groups.map(([g, list]) => (
            <div key={g} className="look-group">
              <h4>{g}</h4>
              <div className="look-grid" role="radiogroup" aria-label={g}>
                {list.map((s) => (
                  <button key={s.id} role="radio" aria-checked={sel === s.id} className={`look-card ${sel === s.id ? "on" : ""}`} onClick={() => pick(s.id)}>
                    <span className="ln">{s.name}</span>
                    <span className="ld">{s.description}</span>
                    {s.fit && <span className="lf">{s.fit}</span>}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="field" style={{ marginTop: 14 }}>
          <label htmlFor="look-notes">Your notes <span className="opt">Optional · added to every shot, e.g. “keep Sege's beard and linen shirt”</span></label>
          <input id="look-notes" className="text-input" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
        {director && chosen && (
          <div className="look-advanced">
            <div className="field">
              <label htmlFor="look-prompt">Prompt wording <span className="opt">Sent with every shot · leave empty for the library wording</span></label>
              <textarea id="look-prompt" className="text-input" rows={3} placeholder={chosen.prompt} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="look-avoid">Avoid <span className="opt">Negative prompt when the model supports one</span></label>
              <input id="look-avoid" className="text-input" placeholder={chosen.avoid} value={avoid} onChange={(e) => setAvoid(e.target.value)} />
            </div>
          </div>
        )}
        <div className="sheet-actions">
          <button className="btn ghost" onClick={onCancel}>Cancel</button>
          <button className="btn primary" onClick={save} disabled={!sel}>Use {chosen?.name ?? "this look"}</button>
        </div>
      </div>
    </div>
  );
}
