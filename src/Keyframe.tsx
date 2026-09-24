import { useEffect, useState } from "react";
import { api, AUTO_IMAGE_MODEL, errorText, type CatalogItem, type Job, type KeyStatus, type Shot } from "./api";
import { ACTIVE_STATES, ConfirmRender, defaultProvider, PROVIDER_NAME } from "./Render";
import * as I from "./icons";

/**
 * Keyframe first: a still of the shot (cheap, fast) that the user approves before paying for video.
 * The approved still becomes the video's first frame or lead reference, which keeps characters and
 * composition consistent.
 */
export function KeyframePanel({ dir, shot, plan, jobs, keys, director, approved, onJobs, onApproved, onSettings }: {
  dir: string; shot: Shot; plan: string; jobs: Job[]; keys: KeyStatus; director: boolean;
  approved: string | null; onJobs: (j: Job[]) => void; onApproved: (ref: string | null) => void; onSettings: () => void;
}) {
  const [provider, setProvider] = useState(defaultProvider(keys));
  const [model, setModel] = useState(AUTO_IMAGE_MODEL[defaultProvider(keys)]);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState("");
  const stills = jobs.filter((j) => j.shot_id === shot.id && j.kind === "image" && j.state !== "dismissed")
    .sort((a, b) => b.created - a.created);
  const busy = stills.some((j) => ACTIVE_STATES.includes(j.state));

  useEffect(() => { if (director) api.renderCatalog(provider, "image").then(setCatalog).catch(() => setCatalog([])); }, [director, provider]);

  const make = async () => {
    setConfirm(false); setError("");
    try { onJobs(await api.queueRender(dir, [shot.id], provider, model, {}, [], "image")); } catch (e) { setError(errorText(e)); }
  };
  const approve = async (ref: string | null) => {
    try { await api.setKeyframe(dir, plan, shot.id, ref); onApproved(ref); } catch (e) { setError(errorText(e)); }
  };
  const hasKey = keys[provider as keyof KeyStatus];

  return (
    <div className="insp-section render-panel">
      <h4>Keyframe</h4>
      <p className="dim" style={{ margin: "0 0 10px" }}>Recommended: make a still of this shot first, approve it, then render the video from it.</p>
      {director && (
        <>
          <div className="seg" role="group" aria-label="Image provider">
            {(["fal", "kie", "google"] as const).map((p) => (
              <button key={p} className={provider === p ? "on" : ""} onClick={() => { setProvider(p); setModel(AUTO_IMAGE_MODEL[p]); }}>
                {PROVIDER_NAME[p]}{!keys[p] && <span className="dim"> · no key</span>}</button>
            ))}
          </div>
          <input className="text-input" list="image-models" value={model} onChange={(e) => setModel(e.target.value)} aria-label="Image model" />
          <datalist id="image-models">{catalog.map((c) => <option key={c.model} value={c.model}>{c.title}</option>)}</datalist>
          <div className="hint-row">{catalog.length ? `${catalog.length} image models` : "Loading models…"}</div>
        </>
      )}
      <div className="stills">
        {stills.map((j) => {
          const ref = j.output ? `project:${j.output}` : null;
          const isApproved = !!ref && ref === approved;
          return (
            <div key={j.id} className={`still ${isApproved ? "approved" : ""}`}>
              {j.state === "ready" && j.output ? <img src={api.mediaUrl(`${dir}/${j.output}`)} alt={`Keyframe for ${shot.id}`} />
                : <div className="still-wait">{ACTIVE_STATES.includes(j.state) ? <><span className="spin" /> Making still…</> : j.error ?? j.state}</div>}
              {j.state === "ready" && ref && (
                <button className={`btn small ${isApproved ? "" : "primary"}`} onClick={() => approve(isApproved ? null : ref)}>
                  {isApproved ? <><I.Check size={12} /> Approved · click to clear</> : "Use for this shot"}</button>
              )}
            </div>
          );
        })}
      </div>
      {error && <div className="error-text">{error}</div>}
      <div className="render-actions">
        {!hasKey ? <button className="btn" onClick={onSettings}>Add {PROVIDER_NAME[provider]} key</button>
          : <button className="btn" onClick={() => setConfirm(true)} disabled={busy}>{stills.length ? "Make another still" : "Make a keyframe"}</button>}
      </div>
      {confirm && <ConfirmRender count={1} seconds={0} provider={provider} model={model} kind="image"
                                 onCancel={() => setConfirm(false)} onConfirm={make} dir={dir} shots={[shot.id]} modelId={model} />}
    </div>
  );
}
