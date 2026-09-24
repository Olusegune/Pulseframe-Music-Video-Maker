import { useEffect, useMemo, useState } from "react";
import { api, AUTO_MODEL, errorText, type CatalogItem, type Job, type KeyStatus, type Manifest, type ManifestInput, type Shot } from "./api";
import * as I from "./icons";

export const PROVIDER_NAME: Record<string, string> = { fal: "fal.ai", kie: "Kie.ai" };
export const ACTIVE_STATES = ["queued", "submitting", "submitted"];

/** Latest non-dismissed job for each shot of the current plan. */
export function latestJobs(jobs: Job[], plan: string): Map<string, Job> {
  const m = new Map<string, Job>();
  for (const j of jobs) {
    if (j.plan !== plan || j.state === "dismissed") continue;
    const cur = m.get(j.shot_id);
    if (!cur || j.created >= cur.created) m.set(j.shot_id, j);
  }
  return m;
}

export function JobChip({ job }: { job?: Job }) {
  if (!job) return null;
  switch (job.state) {
    case "queued": return <span className="chip"><I.Circle size={12} /> Queued</span>;
    case "submitting":
    case "submitted": return <span className="chip gen"><span className="spin" /> Generating</span>;
    case "ready": return <span className="chip ready"><I.Check size={12} /> Ready</span>;
    case "uncertain": return <span className="chip review"><I.Alert size={12} /> Check needed</span>;
    case "failed": return <span className="chip failed"><I.Alert size={12} /> Failed</span>;
    default: return null;
  }
}

/** Pick the provider to use by default: whichever has a key, fal first. */
export const defaultProvider = (keys: KeyStatus) => (keys.fal ? "fal" : keys.kie ? "kie" : "fal");

// ---------------------------------------------------------------- inspector panel

export function RenderPanel({ dir, shot, jobs, director, keys, onQueued, onSettings }: {
  dir: string; shot: Shot; jobs: Job[]; director: boolean; keys: KeyStatus;
  onQueued: (jobs: Job[]) => void; onSettings: () => void;
}) {
  const [provider, setProvider] = useState(defaultProvider(keys));
  const [model, setModel] = useState(AUTO_MODEL[defaultProvider(keys)]);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [auto, setAuto] = useState<Record<string, unknown>>({});
  const [pins, setPins] = useState<Record<string, unknown>>({});
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [showRaw, setShowRaw] = useState(false);

  const history = jobs.filter((j) => j.shot_id === shot.id && j.state !== "dismissed").sort((a, b) => b.created - a.created);
  const active = history.find((j) => ACTIVE_STATES.includes(j.state));
  const hasKey = keys[provider as keyof KeyStatus];

  useEffect(() => { setPins({}); }, [shot.id]);
  // Settle edits before asking the engine for a fresh preview.
  const [settled, setSettled] = useState(pins);
  useEffect(() => { const t = setTimeout(() => setSettled(pins), 500); return () => clearTimeout(t); }, [pins]);
  useEffect(() => { if (director) api.renderCatalog(provider).then(setCatalog).catch(() => setCatalog([])); }, [director, provider]);

  // What PULSEFRAME would send (Auto values) — free, uploads nothing.
  useEffect(() => {
    let live = true;
    setBusy("Reading model…"); setError("");
    api.renderPreview(dir, shot.id, provider, model, settled)
      .then((r) => { if (!live) return; setManifest(r.manifest); setAuto(r.payload); })
      .catch((e) => live && setError(errorText(e)))
      .finally(() => live && setBusy(""));
    return () => { live = false; };
  }, [dir, shot.id, provider, model, settled]);

  const send = async () => {
    setConfirm(false); setBusy("Queuing…"); setError("");
    try { onQueued(await api.queueRender(dir, [shot.id], provider, model, pins)); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(""); }
  };
  const resolve = async (job: Job, action: "retry" | "dismiss") => {
    try { onQueued([await api.resolveJob(dir, job.id, action)]); } catch (e) { setError(errorText(e)); }
  };

  const modelTitle = manifest?.title ?? model;
  return (
    <div className="insp-section render-panel">
      <h4>Render</h4>
      {!director ? (
        <div className="kv"><span className="k">Renderer</span><span className="v">Auto · {PROVIDER_NAME[provider]} {modelTitle}</span></div>
      ) : (
        <>
          <div className="seg" role="group" aria-label="Provider">
            {(["fal", "kie"] as const).map((p) => (
              <button key={p} className={provider === p ? "on" : ""} onClick={() => { setProvider(p); setModel(AUTO_MODEL[p]); setPins({}); }}>
                {PROVIDER_NAME[p]}{!keys[p] && <span className="dim"> · no key</span>}
              </button>
            ))}
          </div>
          <label className="mini-label" htmlFor="model">Model</label>
          <input id="model" className="text-input" list="model-list" value={model}
                 onChange={(e) => setModel(e.target.value)} onBlur={(e) => { if (!e.target.value) setModel(AUTO_MODEL[provider]); setPins({}); }} />
          <datalist id="model-list">{catalog.map((c) => <option key={c.model} value={c.model}>{c.title}</option>)}</datalist>
          <div className="hint-row">{catalog.length ? `${catalog.length} ${PROVIDER_NAME[provider]} video models` : "Loading models…"} · Auto = {AUTO_MODEL[provider]}</div>
          {manifest && <ModelInputs manifest={manifest} auto={auto} pins={pins} setPins={setPins} />}
          <button className="btn ghost small" onClick={() => setShowRaw((v) => !v)}>{showRaw ? "Hide" : "Show"} exact request</button>
          {showRaw && <pre className="raw">{JSON.stringify(auto, null, 1)}</pre>}
        </>
      )}

      {error && <div className="error-text">{error}</div>}
      <div className="render-actions">
        {!hasKey ? <button className="btn" onClick={onSettings}>Add {PROVIDER_NAME[provider]} key</button> :
          <button className="btn primary" disabled={!!busy || !!active || !manifest} onClick={() => setConfirm(true)}>
            {active ? "Rendering…" : history.some((j) => j.state === "ready") ? "Render a new take" : "Render this shot"}</button>}
        {busy && <span className="dim">{busy}</span>}
      </div>

      {history.length > 0 && (
        <div className="takes">
          {history.map((j) => (
            <div key={j.id} className="take">
              <div className="take-top"><JobChip job={j} /><span className="dim num">{PROVIDER_NAME[j.provider]} · {shortModel(j.model)}</span></div>
              {j.error && <div className="take-err">{j.error}</div>}
              {j.cost != null && <div className="dim num">Cost: {j.cost} {j.cost_unit ?? ""}</div>}
              {(j.state === "failed" || j.state === "uncertain") && (
                <div className="take-actions">
                  <button className="btn small" onClick={() => resolve(j, "retry")}>{j.state === "uncertain" ? "Send again" : "Retry"}</button>
                  <button className="btn ghost small" onClick={() => resolve(j, "dismiss")}>Dismiss</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {confirm && <ConfirmRender count={1} seconds={Number(auto[manifest?.roles.duration ?? "duration"] ?? 0)}
                                 provider={provider} model={modelTitle} onCancel={() => setConfirm(false)} onConfirm={send} />}
    </div>
  );
}

const shortModel = (m: string) => m.split("/").slice(-2).join("/");

/** Every input the model exposes, generated from its manifest. Auto values come from the Shot Contract. */
function ModelInputs({ manifest, auto, pins, setPins }: {
  manifest: Manifest; auto: Record<string, unknown>; pins: Record<string, unknown>; setPins: (p: Record<string, unknown>) => void;
}) {
  const roleOf = useMemo(() => Object.fromEntries(Object.entries(manifest.roles).map(([r, f]) => [f, r])), [manifest]);
  const pin = (name: string, v: unknown) => setPins({ ...pins, [name]: v });
  const unpin = (name: string) => { const n = { ...pins }; delete n[name]; setPins(n); };
  return (
    <div className="model-inputs">
      {manifest.inputs.map((f) => {
        const pinned = f.name in pins;
        const value = pinned ? pins[f.name] : auto[f.name] ?? f.default;
        const origin = pinned ? "Pinned" : f.name in auto ? "Auto" : f.default !== null && f.default !== undefined ? "Default" : "Unset";
        return (
          <div key={f.name} className={`mi ${pinned ? "pinned" : ""}`}>
            <div className="mi-head">
              <span className="mi-name" title={f.description}>{f.name}{f.required && " *"}</span>
              {roleOf[f.name] && <span className="mi-role">{roleOf[f.name].replace("_", " ")}</span>}
              <span className={`mi-origin ${origin.toLowerCase()}`}>{origin}</span>
              {pinned && <button className="link" onClick={() => unpin(f.name)}>Reset</button>}
            </div>
            <InputWidget f={f} value={value} onChange={(v) => pin(f.name, v)} />
            {f.description && <div className="mi-desc">{f.description.length > 160 ? f.description.slice(0, 157) + "…" : f.description}</div>}
          </div>
        );
      })}
    </div>
  );
}

function InputWidget({ f, value, onChange }: { f: ManifestInput; value: unknown; onChange: (v: unknown) => void }) {
  if (f.enum?.length) {
    return <select className="text-input" value={String(value ?? "")} onChange={(e) => {
      const raw = f.enum!.find((x) => String(x) === e.target.value);
      onChange(raw);
    }}>{f.enum.map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}</select>;
  }
  if (f.type === "boolean") {
    return <label className="toggle"><input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
      <span>{value ? "On" : "Off"}</span></label>;
  }
  if (f.type === "integer" || f.type === "number") {
    return <input className="text-input" type="number" value={value === null || value === undefined ? "" : String(value)}
                  min={f.minimum ?? undefined} max={f.maximum ?? undefined}
                  onChange={(e) => onChange(e.target.value === "" ? null : f.type === "integer" ? parseInt(e.target.value) : parseFloat(e.target.value))} />;
  }
  if (f.type === "array") {
    const list = Array.isArray(value) ? value.map(String) : [];
    return <textarea className="text-input mono" rows={Math.max(2, list.length)} placeholder="One URL per line"
                     value={list.join("\n")} onChange={(e) => onChange(e.target.value.split("\n").map((x) => x.trim()).filter(Boolean))} />;
  }
  const long = f.name.includes("prompt");
  return long
    ? <textarea className="text-input" rows={6} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
    : <input className="text-input" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />;
}

// ---------------------------------------------------------------- confirmation

export function ConfirmRender({ count, seconds, provider, model, onCancel, onConfirm }: {
  count: number; seconds: number; provider: string; model: string; onCancel: () => void; onConfirm: () => void;
}) {
  return (
    <div className="overlay" onClick={onCancel}>
      <div className="sheet glass" role="dialog" aria-label="Confirm render" onClick={(e) => e.stopPropagation()} style={{ width: "min(480px, calc(100vw - 32px))" }}>
        <h2>Render {count === 1 ? "this shot" : `${count} shots`}?</h2>
        <p className="sub">
          {PROVIDER_NAME[provider]} · {model}<br />
          {count === 1 && seconds ? `${seconds} s of video, trimmed to the beat in the edit. ` : ""}
          {PROVIDER_NAME[provider]} bills your account for each render. PULSEFRAME sends each shot once and never
          re-sends a render automatically.
        </p>
        <div className="sheet-actions">
          <button className="btn ghost" onClick={onCancel}>Cancel</button>
          <button className="btn primary" onClick={onConfirm} autoFocus>Render</button>
        </div>
      </div>
    </div>
  );
}
