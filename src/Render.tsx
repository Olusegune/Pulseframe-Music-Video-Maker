import { useEffect, useMemo, useState } from "react";
import { api, AUTO_LIPSYNC_MODEL, AUTO_MODEL, errorText, type CatalogItem, type Estimate, type Job, type KeyStatus, type Manifest, type ManifestInput, type Shot } from "./api";
import * as I from "./icons";
import { needsAttention } from "./Review";
import { MediaInput, mediaKind } from "./Media";

export const PROVIDER_NAME: Record<string, string> = { fal: "fal.ai", kie: "Kie.ai", google: "Google" };
export const ACTIVE_STATES = ["queued", "submitting", "submitted"];

/** Latest non-dismissed job for each shot of the current plan. */
export function latestJobs(jobs: Job[], plan: string): Map<string, Job> {
  const m = new Map<string, Job>();
  for (const j of jobs) {
    if (j.plan !== plan || j.state === "dismissed" || j.kind === "image") continue;
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
export const defaultProvider = (keys: KeyStatus) => (keys.fal ? "fal" : keys.kie ? "kie" : keys.google ? "google" : "fal");

// ---------------------------------------------------------------- inspector panel

export function RenderPanel({ dir, shot, jobs, director, keys, onQueued, onSettings, lookId, keyframeKey }: {
  dir: string; shot: Shot; jobs: Job[]; director: boolean; keys: KeyStatus;
  onQueued: (jobs: Job[]) => void; onSettings: () => void; lookId: string; keyframeKey?: string | null;
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
  const [lipSync, setLipSync] = useState(false);
  const [singing, setSinging] = useState<{ performer: string; lyrics: string[] } | null>(null);
  const [keyframeRef, setKeyframeRef] = useState<string | null>(null);
  const [lipFor, setLipFor] = useState<Job | null>(null);
  const lipProvider = keys.fal ? "fal" : "kie";
  const lipsync = async () => {
    const src = lipFor!;
    setLipFor(null); setError("");
    try { onQueued(await api.queueRender(dir, [shot.id], lipProvider, AUTO_LIPSYNC_MODEL[lipProvider], {}, [], "lipsync", src.id)); }
    catch (e) { setError(errorText(e)); }
  };

  const history = jobs.filter((j) => j.shot_id === shot.id && j.state !== "dismissed" && j.kind !== "image").sort((a, b) => b.created - a.created);
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
      .then((r) => { if (!live) return; setManifest(r.manifest); setAuto(r.payload); setLipSync(!!r.lip_sync); setSinging(r.singing ?? null); setKeyframeRef((r as { keyframe?: string }).keyframe ?? null); })
      .catch((e) => live && setError(errorText(e)))
      .finally(() => live && setBusy(""));
    return () => { live = false; };
  }, [dir, shot.id, provider, model, settled, lookId, keyframeKey]);

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
            {(["fal", "kie", "google"] as const).map((p) => (
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
          {keyframeRef && <div className="lip-note" style={{ color: "var(--signal-bright)", background: "var(--signal-wash)" }}>
            <I.Check size={14} /> Starts from your approved keyframe.</div>}
          {singing && <div className="lip-note"><I.Note size={14} /> {lipSync ? `Lip-sync: ${singing.performer} sings “${singing.lyrics.join(" / ")}” to the song slice under this shot.`
            : `${singing.performer} sings here, but this model can't take reference audio, so lip-sync is off.`}</div>}
          {manifest && <ModelInputs dir={dir} manifest={manifest} auto={auto} pins={pins} setPins={setPins} />}
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
              {j.state === "ready" && j.review?.reviewed && (
                <div className={`take-err ${needsAttention(j) ? "warn" : ""}`}>
                  {j.review.accepted ? "Kept by you. " : ""}{j.review.summary}
                  {needsAttention(j) && <ul className="ri-issues">{(j.review.issues ?? []).map((i, k) => <li key={k}>{i.detail}</li>)}</ul>}
                </div>)}
              {j.state === "ready" && j.look && j.look !== lookId &&
                <div className="take-err" style={{ color: "var(--warning)" }}>Rendered in an earlier look. Render a new take to match.</div>}
              {j.cost != null && <div className="dim num">Cost: {j.cost} {j.cost_unit ?? ""}</div>}
              {j.kind === "lipsync" && <div className="dim">Lip-synced version</div>}
              {j.state === "ready" && j.kind !== "lipsync" && keys[provider as keyof KeyStatus] && (keys.fal || keys.kie) && (
                <div className="take-actions">
                  <button className="btn small ghost" onClick={() => setLipFor(j)}>Lip-sync this take…</button>
                </div>)}
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

      {lipFor && <ConfirmRender count={1} seconds={0} provider={lipProvider} kind="lipsync"
                                model={`${AUTO_LIPSYNC_MODEL[lipProvider]} · re-syncs the mouth to the isolated vocal under this shot`}
                                onCancel={() => setLipFor(null)} onConfirm={lipsync} />}
      {confirm && <ConfirmRender count={1} seconds={Number(auto[manifest?.roles.duration ?? "duration"] ?? 0)}
                                 provider={provider} model={modelTitle} onCancel={() => setConfirm(false)} onConfirm={send}
                                 dir={dir} shots={[shot.id]} modelId={model} />}
    </div>
  );
}

const shortModel = (m: string) => m.split("/").slice(-2).join("/");

/** Every input the model exposes, generated from its manifest. Auto values come from the Shot Contract. */
const GROUPS: [string, (f: ManifestInput, role?: string) => boolean][] = [
  ["Prompt", (_f, r) => r === "prompt" || r === "negative_prompt"],
  ["References", (f) => mediaKind(f) !== null],
  ["Format & quality", (f, r) => ["duration", "aspect_ratio", "resolution"].includes(r ?? "") || /fps|frame_rate|quality|bitrate|codec|size/.test(f.name)],
  ["Motion & camera", (f) => /camera|motion|movement|strength|dynamic/.test(f.name)],
  ["Everything else", () => true],
];

function ModelInputs({ dir, manifest, auto, pins, setPins }: {
  dir: string; manifest: Manifest; auto: Record<string, unknown>; pins: Record<string, unknown>; setPins: (p: Record<string, unknown>) => void;
}) {
  const roleOf = useMemo(() => Object.fromEntries(Object.entries(manifest.roles).map(([r, f]) => [f, r])), [manifest]);
  const pin = (name: string, v: unknown) => setPins({ ...pins, [name]: v });
  const unpin = (name: string) => { const n = { ...pins }; delete n[name]; setPins(n); };
  const grouped = GROUPS.map(([g]) => [g, [] as ManifestInput[]] as const);
  for (const f of manifest.inputs) grouped[GROUPS.findIndex(([, t]) => t(f, roleOf[f.name]))][1].push(f);
  return (
    <div className="model-inputs">
      {grouped.filter(([, list]) => list.length).map(([g, list]) => <div key={g} className="mi-group"><h5>{g}</h5>
      {list.map((f) => {
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
            {mediaKind(f) ? <MediaInput dir={dir} kind={mediaKind(f)!} multiple={f.type === "array"} value={value} max={f.max_items}
                                        onChange={(v) => pin(f.name, v)} />
              : <InputWidget f={f} value={value} onChange={(v) => pin(f.name, v)} />}
            {f.description && <div className="mi-desc">{f.description.length > 160 ? f.description.slice(0, 157) + "…" : f.description}</div>}
          </div>
        );
      })}</div>)}
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

export function ConfirmRender({ count, seconds, provider, model, onCancel, onConfirm, dir, shots, modelId, kind = "video" }: {
  count: number; seconds: number; provider: string; model: string; onCancel: () => void; onConfirm: () => void;
  dir?: string; shots?: string[]; modelId?: string | null; kind?: "video" | "image" | "lipsync";
}) {
  const [est, setEst] = useState<Estimate | null>(null);
  const [estErr, setEstErr] = useState(false);
  useEffect(() => {
    if (!dir || !shots?.length || kind === "lipsync") return;
    api.renderEstimate(dir, shots, provider, modelId ?? null, kind).then(setEst).catch(() => setEstErr(true));
  }, [dir, shots, provider, modelId, kind]);
  const big = (est?.usd ?? 0) >= 25;
  return (
    <div className="overlay" onClick={onCancel}>
      <div className="sheet glass" role="dialog" aria-label="Confirm render" onClick={(e) => e.stopPropagation()} style={{ width: "min(500px, calc(100vw - 32px))" }}>
        <h2>{kind === "lipsync" ? "Lip-sync this take?" : kind === "image" ? "Make a keyframe?" : `Render ${count === 1 ? "this shot" : `${count} shots`}?`}</h2>
        <p className="sub">
          {PROVIDER_NAME[provider]} · {model}<br />
          {count === 1 && seconds ? `${seconds} s of video, trimmed to the beat in the edit.` : ""}
        </p>
        <div className={`cost ${big ? "big" : ""}`}>
          {!dir ? null : est ? (
            est.usd != null ? <>
              <div className="cost-n num">≈ ${est.usd.toFixed(2)}</div>
              <div className="dim">{count > 1 ? `about $${(est.usd / count).toFixed(2)} per shot · ` : ""}{est.basis}</div>
              {est.lipsync_shots ? <div className="dim">Includes a dedicated lip-sync pass for {est.lipsync_shots === 1 && count === 1 ? "this singing close-up"
                : `${est.lipsync_shots} singing close-up${est.lipsync_shots > 1 ? "s" : ""}`}.</div> : null}
            </> : <>
              <div className="cost-n">{provider === "kie" ? "Billed in Kie credits" : provider === "google" ? "Billed by Google" : "Price not published"}</div>
              <div className="dim">{est.basis}{est.kie_credits != null ? ` Balance: ${est.kie_credits.toLocaleString()} credits.` : ""}</div>
            </>
          ) : estErr ? <div className="dim">Couldn't fetch the price right now.</div> : <div className="dim">Checking price…</div>}
        </div>
        <p className="dim" style={{ marginTop: 10 }}>{PROVIDER_NAME[provider]} bills your account. PULSEFRAME sends each shot once and never
          re-sends a render automatically.</p>
        <div className="sheet-actions">
          <button className="btn ghost" onClick={onCancel}>Cancel</button>
          <button className="btn primary" onClick={onConfirm} autoFocus={!big}>
            {est?.usd != null ? `Render · ≈ $${est.usd.toFixed(2)}` : "Render"}</button>
        </div>
      </div>
    </div>
  );
}
