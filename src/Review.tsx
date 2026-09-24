import { useState } from "react";
import { api, errorText, fmtTime, type Job, type KeyStatus, type Shot } from "./api";
import { ConfirmRender, defaultProvider } from "./Render";
import * as I from "./icons";

/** A ready take whose review found something and the user hasn't accepted it. */
export const needsAttention = (j?: Job) =>
  !!j && j.state === "ready" && !!j.review?.reviewed && !j.review.accepted &&
  (j.review.status === "needs_attention" || j.review.status === "minor");

const KIND: Record<string, string> = {
  character: "Character", wardrobe: "Wardrobe", environment: "Setting", look: "Look", action: "Action",
  artifact: "Artifact", text: "On-screen text", framing: "Framing", technical: "Technical",
};

/** PRD §27: only useful feedback, one action per problem, and Fix All. */
export function ReviewSheet({ dir, shots, latest, keys, onSelect, onJobs, onClose }: {
  dir: string; shots: Shot[]; latest: Map<string, Job>; keys: KeyStatus;
  onSelect: (id: string) => void; onJobs: (j: Job[]) => void; onClose: () => void;
}) {
  const [confirm, setConfirm] = useState<string[] | null>(null);
  const [error, setError] = useState("");
  const flagged = shots.map((s) => ({ shot: s, job: latest.get(s.id) })).filter((x) => needsAttention(x.job));
  const major = flagged.filter((x) => x.job!.review!.status === "needs_attention");
  const ready = shots.filter((s) => latest.get(s.id)?.state === "ready").length;
  const visualOff = !keys.openai;

  const fix = async (ids: string[]) => {
    setConfirm(null); setError("");
    try {
      for (const id of ids) {
        const j = latest.get(id)!;
        // Same model as the flagged take, plus the reviewer's corrections.
        onJobs(await api.queueRender(dir, [id], j.provider, j.model, j.overrides ?? {}, j.review?.fixes ?? []));
      }
    } catch (e) { setError(errorText(e)); }
  };
  const accept = async (j: Job) => {
    try { onJobs([await api.resolveJob(dir, j.id, "accept")]); } catch (e) { setError(errorText(e)); }
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet glass review-sheet" role="dialog" aria-label="Review" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
          <div>
            <h2>{flagged.length ? `${flagged.length} shot${flagged.length > 1 ? "s" : ""} may need attention` : "Review"}</h2>
            <p className="sub">{ready} of {shots.length} shots rendered and checked.
              {visualOff && " Add an OpenAI key in Settings to also check characters, wardrobe, look and artifacts."}</p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><I.Close /></button>
        </div>

        {flagged.length === 0 ? (
          <div className="review-empty"><I.Check size={20} /> {ready ? "Every checked take looks usable." : "Nothing rendered yet."}</div>
        ) : (
          <div className="review-list">
            {flagged.map(({ shot, job }) => (
              <div key={shot.id} className={`review-item ${job!.review!.status === "needs_attention" ? "major" : ""}`}>
                <button className="ri-head" onClick={() => { onSelect(shot.id); onClose(); }} title="Show in Studio">
                  <span className="chip num">{shot.id}</span>
                  <span className="dim num">{fmtTime(shot.start)}</span>
                  <span className="ri-sum">{job!.review!.summary}</span>
                </button>
                <ul className="ri-issues">
                  {(job!.review!.issues ?? []).map((i, k) => (
                    <li key={k}><span className={`sev ${i.severity}`}>{KIND[i.kind] ?? i.kind}</span> {i.detail}</li>
                  ))}
                </ul>
                <div className="take-actions">
                  <button className="btn small primary" onClick={() => setConfirm([shot.id])}>Fix</button>
                  <button className="btn small ghost" onClick={() => accept(job!)}>Keep this take</button>
                </div>
              </div>
            ))}
          </div>
        )}
        {error && <div className="error-text">{error}</div>}
        <div className="sheet-actions">
          <button className="btn ghost" onClick={onClose}>Close</button>
          {flagged.length > 0 && <button className="btn primary" onClick={() => setConfirm(flagged.map((x) => x.shot.id))}>
            Fix all ({flagged.length})</button>}
        </div>
        {major.length === 0 && flagged.length > 0 && <p className="dim" style={{ marginTop: 8 }}>All flags are minor; these takes are usable as they are.</p>}

        {confirm && <ConfirmRender count={confirm.length} seconds={0} provider={latest.get(confirm[0])?.provider ?? defaultProvider(keys)}
                                   model="same model as the flagged take, with the reviewer's corrections"
                                   onCancel={() => setConfirm(null)} onConfirm={() => fix(confirm)} />}
      </div>
    </div>
  );
}
