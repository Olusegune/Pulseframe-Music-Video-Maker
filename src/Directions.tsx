import { useEffect, useState } from "react";
import { api, errorText, type Concept, type EngineEvent, type LoadedProject } from "./api";
import { lookName, useStyles } from "./Looks";
import * as I from "./icons";

const LEVEL: Record<string, string> = { performance: "Performance-led", hybrid: "Performance + story", narrative: "Story-led" };

/**
 * PRD §10–13 for songs without a script: three directions -> pick one -> treatment and shot plan.
 * Shown in the Studio until the project has a plan.
 */
export function CreativeDirections({ project, onPlanned, onSettings }: {
  project: LoadedProject; onPlanned: () => void; onSettings: () => void;
}) {
  const styles = useStyles();
  const [concepts, setConcepts] = useState<Concept[]>(project.concepts?.concepts ?? []);
  const [pick, setPick] = useState<number | null>(null);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const un = api.onEngine((e: EngineEvent) => { if ((e.task === "concepts" || e.task === "treatment") && e.stage) setBusy(cap(e.stage)); });
    return () => { un.then((f) => f()); };
  }, []);

  const imagine = async () => {
    const keys = await api.keyStatus();
    if (!keys.openai) { onSettings(); return; }
    setError(""); setBusy("Listening to the song…"); setPick(null);
    try { setConcepts((await api.creativeDirections(project.dir, notes)).concepts); } catch (e) { setError(errorText(e)); }
    finally { setBusy(""); }
  };
  const develop = async () => {
    if (pick === null) return;
    setError(""); setBusy("Writing the treatment…");
    try {
      const c = concepts[pick];
      // Adopt the direction's look unless the user already chose one.
      const current = typeof project.project.look === "object" ? project.project.look.style : "auto";
      if (current === "auto" && c.suggested_look && c.suggested_look !== "auto") await api.setLook(project.dir, { style: c.suggested_look });
      await api.writeTreatment(project.dir, pick, notes);
      onPlanned();
    } catch (e) { setError(errorText(e)); setBusy(""); }
  };

  return (
    <div className="directions">
      {concepts.length === 0 ? (
        <div className="dir-intro">
          <h2>How should this song look?</h2>
          <p className="sub">PULSEFRAME will propose three different directions for “{project.project.title}”. You choose one, and it
            writes the treatment and plans every shot on the beat.</p>
          <textarea className="text-input" rows={3} placeholder="Optional: anything you want, e.g. “set in Lagos, no dancing, hopeful ending”"
                    value={notes} onChange={(e) => setNotes(e.target.value)} />
          <div className="sheet-actions">
            <button className="btn hero" onClick={imagine} disabled={!!busy}>{busy || "Show me three directions"}</button>
          </div>
        </div>
      ) : (
        <>
          <div className="dir-head">
            <h2>Choose a direction</h2>
            <button className="btn ghost" onClick={imagine} disabled={!!busy}>Three new ideas</button>
          </div>
          <div className="dir-grid" role="radiogroup" aria-label="Directions">
            {concepts.map((c, i) => (
              <button key={i} role="radio" aria-checked={pick === i} className={`dir-card ${pick === i ? "on" : ""}`}
                      onClick={() => setPick(i)} disabled={!!busy}>
                <span className="dir-level">{LEVEL[c.narrative_level] ?? c.narrative_level}</span>
                <span className="dir-title">{c.title}</span>
                <span className="dir-premise">{c.premise}</span>
                <span className="dir-hero">“{c.hero_frame}”</span>
                <span className="dir-row"><b>Mood</b> {c.mood}</span>
                <span className="dir-row"><b>Performance</b> {c.performance_approach}</span>
                <span className="dir-row"><b>Camera</b> {c.cinematic_style}</span>
                <span className="dir-row"><b>World</b> {c.environment}</span>
                <span className="dir-row"><b>Movement</b> {c.movement}</span>
                <span className="dir-palette">{c.palette.map((p) => <i key={p}>{p}</i>)}</span>
                <span className="dir-look">Look: {lookName(styles, { style: c.suggested_look })}</span>
              </button>
            ))}
          </div>
          <div className="dir-foot">
            <input className="text-input" placeholder="Notes for the treatment (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
            <button className="btn hero" onClick={develop} disabled={pick === null || !!busy}>
              {busy || (pick === null ? "Pick a direction" : `Direct “${concepts[pick].title}”`)}</button>
          </div>
        </>
      )}
      {busy && <div className="progress indet" style={{ marginTop: 12 }}><i /></div>}
      {error && <div className="error-text">{error}</div>}
      <p className="dim" style={{ marginTop: 12 }}><I.Script size={12} /> Have a script already? Create the project again and add it; PULSEFRAME will follow it instead.</p>
    </div>
  );
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1) + "…";
