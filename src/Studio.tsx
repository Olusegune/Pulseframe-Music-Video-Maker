import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, errorText, fmtTime, type EngineEvent, type LoadedProject, type Plan, type Scene, type Shot, type SongMap } from "./api";
import * as I from "./icons";
import { ACTIVE_STATES, ConfirmRender, defaultProvider, JobChip, latestJobs, RenderPanel } from "./Render";
import { AUTO_MODEL, type Job, type KeyStatus } from "./api";
import { ExportSheet } from "./Export";
import { LookPicker, lookName, normalizeLook, useStyles } from "./Looks";
import { needsAttention, ReviewSheet } from "./Review";

type Selection = { kind: "shot"; id: string } | { kind: "section"; index: number } | null;

export function Studio({ project, onHome, onSettings, onReload }: {
  project: LoadedProject; onHome: () => void; onSettings: () => void; onReload: () => void;
}) {
  const map = project.song_map;
  const plan: Plan | null = project.directed ?? project.production;
  const scenes = plan?.scenes ?? [];
  const shots = useMemo(() => scenes.flatMap((s) => s.shots), [scenes]);

  const audio = useRef<HTMLAudioElement | null>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [sel, setSel] = useState<Selection>(null);
  const [director, setDirector] = useState(false);
  const [inspector, setInspector] = useState(true);
  const [job, setJob] = useState<{ title: string; detail: string } | null>(null);
  const [error, setError] = useState("");
  const [jobs, setJobs] = useState<Job[]>(project.jobs ?? []);
  const [keys, setKeys] = useState<KeyStatus>({ openai: false, fal: false, kie: false });
  const [confirmAll, setConfirmAll] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [lookOpen, setLookOpen] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [look, setLook] = useState(normalizeLook(project.project.look));
  const styles = useStyles();
  const saveLook = async (l: typeof look) => {
    setLookOpen(false);
    try { await api.setLook(project.dir, l); setLook(l); } catch (e) { setError(errorText(e)); }
  };
  const planName = project.directed ? "directed" : "production";
  const latest = useMemo(() => latestJobs(jobs, planName), [jobs, planName]);

  const mergeJobs = useCallback((incoming: Job[]) => setJobs((cur) => {
    const byId = new Map(cur.map((j) => [j.id, j]));
    for (const j of incoming) byId.set(j.id, { ...byId.get(j.id), ...j });
    return [...byId.values()];
  }), []);

  useEffect(() => {
    const refresh = () => api.keyStatus().then(setKeys).catch(() => {});
    refresh();
    window.addEventListener("pf-keys-changed", refresh);
    // Reconnect to renders that were running when the app closed (PRD §29).
    if ((project.jobs ?? []).some((j) => ACTIVE_STATES.includes(j.state))) api.ensureRenderer(project.dir);
    const un = api.onEngine((e) => { if (e.event === "job" && e.job) mergeJobs([e.job as Job]); });
    return () => { window.removeEventListener("pf-keys-changed", refresh); un.then((f) => f()); };
  }, [project.dir, project.jobs, mergeJobs]);

  useEffect(() => {
    if (!project.song_path) return;
    const a = new Audio(api.mediaUrl(project.song_path));
    a.preload = "auto";
    audio.current = a;
    a.onended = () => setPlaying(false);
    return () => { a.pause(); audio.current = null; };
  }, [project.song_path]);

  useEffect(() => {
    let raf = 0;
    const tick = () => { if (audio.current) setTime(audio.current.currentTime); raf = requestAnimationFrame(tick); };
    if (playing) raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  const toggle = useCallback(() => {
    const a = audio.current;
    if (!a) return;
    if (a.paused) { a.play(); setPlaying(true); } else { a.pause(); setPlaying(false); }
  }, []);
  const seek = useCallback((t: number) => {
    const a = audio.current;
    const c = Math.max(0, Math.min(t, map?.duration ?? 0));
    if (a) a.currentTime = c;
    setTime(c);
  }, [map]);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT" || (e.target as HTMLElement).tagName === "TEXTAREA") return;
      if (e.code === "Space") { e.preventDefault(); toggle(); }
      if (e.code === "ArrowLeft") seek(time - 5);
      if (e.code === "ArrowRight") seek(time + 5);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [toggle, seek, time]);

  const current = shots.find((s) => time >= s.start && time < s.end) ?? null;
  const shown = sel?.kind === "shot" ? shots.find((s) => s.id === sel.id) ?? current : current;
  const lyric = map?.lyrics.find((l) => l.start != null && l.end != null && time >= l.start && time <= l.end + 0.3);

  const directVideo = async () => {
    const keys = await api.keyStatus();
    if (!keys.openai) { onSettings(); return; }
    setError("");
    setJob({ title: "Directing", detail: "Reading the script" });
    const un = await api.onEngine((e: EngineEvent) => {
      if (e.task === "director" && e.stage) setJob({ title: "Directing", detail: capital(e.stage) });
    });
    try { await api.directProject(project.dir); onReload(); }
    catch (e) { setError(errorText(e)); }
    finally { un(); setJob(null); }
  };

  const flagged = shots.filter((s) => (s.flags?.length ?? 0) > 0 || needsAttention(latest.get(s.id))).length;
  const toRender = shots.filter((s) => { const j = latest.get(s.id); return !j || j.state === "failed"; });
  const renderAll = async () => {
    setConfirmAll(false);
    const provider = defaultProvider(keys);
    try { mergeJobs(await api.queueRender(project.dir, toRender.map((s) => s.id), provider, AUTO_MODEL[provider], {})); }
    catch (e) { setError(errorText(e)); }
  };

  return (
    <div className="studio">
      <nav className="rail" aria-label="Main">
        <div className="logo"><I.Mark size={26} /></div>
        <RailBtn icon={<I.Home />} label="Home" onClick={onHome} />
        <RailBtn icon={<I.Folder />} label="Project" disabled />
        <RailBtn icon={<I.Assets />} label="Assets" disabled />
        <RailBtn icon={<I.Studio />} label="Studio" active />
        <RailBtn icon={<I.Review />} label="Review" onClick={() => setReviewing(true)} disabled={!plan}
                 badge={shots.filter((s) => needsAttention(latest.get(s.id))).length} />
        <RailBtn icon={<I.Export />} label="Export" onClick={() => setExporting(true)} disabled={!plan} />
        <div className="spacer" />
        <RailBtn icon={<I.Gear />} label="Settings" onClick={onSettings} />
      </nav>

      <main className="center">
        <header className="topbar">
          <div>
            <div className="title">{project.project.title}</div>
            {map && <div className="meta num">{Math.round(map.bpm)} BPM · {fmtTime(map.duration)} · {shots.length} shots
              {project.directed ? " · Directed" : plan ? " · Planned from script" : ""}</div>}
          </div>
          <div className="grow" />
          <div className="mode-toggle" role="group" aria-label="Mode">
            <button className={!director ? "on" : ""} onClick={() => setDirector(false)}>Simple</button>
            <button className={director ? "on" : ""} onClick={() => setDirector(true)}>Director Mode</button>
          </div>
          {plan && (keys.fal || keys.kie) && <button className="btn" onClick={() => setConfirmAll(true)}
                                   disabled={toRender.length === 0}>Render {toRender.length === shots.length ? "all" : toRender.length} shots</button>}
          {plan && <button className="btn hero" onClick={directVideo} disabled={!!job}>
            {project.directed ? "Direct Again" : "Direct My Video"}</button>}
          <button className="icon-btn" onClick={() => setInspector((v) => !v)} title="Inspector" aria-label="Toggle inspector"><I.Panel /></button>
        </header>

        <div className="viewer-wrap">
          <div className="stage">
          <div className="viewer" style={{ ["--ar" as string]: aspectNum(project.project.aspect_ratio) }}>
            {shown && latest.get(shown.id)?.state === "ready" && latest.get(shown.id)?.output ?
              <Clip src={api.mediaUrl(`${project.dir}/${latest.get(shown.id)!.output}`)} offset={time - shown.start} playing={playing} /> : null}
            {shown ? <Storyboard shot={shown} scene={scenes.find((s) => s.number === shown.scene)} job={latest.get(shown.id)}
                                 hidden={latest.get(shown.id)?.state === "ready"} /> :
              <div className="empty">{plan ? "Press play to preview the song map" : "Add a script or press Direct My Video to plan shots"}</div>}
            <div className="subtitle" style={{ opacity: lyric ? 1 : 0 }}>{lyric?.text ?? ""}</div>
          </div>
          </div>
          <div className="transport glass">
            <button className="icon-btn" onClick={() => seek(0)} aria-label="Back to start"><I.SkipBack size={18} /></button>
            <button className="play-btn" onClick={toggle} aria-label={playing ? "Pause" : "Play"}>{playing ? <I.Pause /> : <I.Play />}</button>
            <button className="icon-btn" onClick={() => seek((map?.duration ?? 0))} aria-label="To end"><I.SkipFwd size={18} /></button>
            <div className="time num">{fmtTime(time)} / {fmtTime(map?.duration ?? 0)}</div>
          </div>
        </div>
      </main>

      <aside className={`inspector ${inspector ? "" : "collapsed"}`} aria-label="Inspector">
        <Inspector sel={sel} shots={shots} scenes={scenes} map={map} plan={plan} director={director} project={project}
                   onClose={() => setSel(null)} lookLabel={lookName(styles, look)} onLook={() => setLookOpen(true)}
                   renderPanel={(s: Shot) => <RenderPanel dir={project.dir} shot={s} jobs={jobs.filter((j) => j.plan === planName)}
                                                          director={director} keys={keys} onQueued={mergeJobs} onSettings={onSettings}
                                                          lookId={look.style} />} />
      </aside>

      <Timeline map={map} shots={shots} time={time} sel={sel} flagged={flagged} latest={latest}
                onSeek={seek} onSelect={(s) => { setSel(s); if (s?.kind === "shot") { const sh = shots.find((x) => x.id === s.id); if (sh) seek(sh.start); } }} />

      {reviewing && <ReviewSheet dir={project.dir} shots={shots} latest={latest} keys={keys} onJobs={mergeJobs}
                                 onSelect={(id) => { setSel({ kind: "shot", id }); const sh = shots.find((x) => x.id === id); if (sh) seek(sh.start); }}
                                 onClose={() => setReviewing(false)} />}
      {lookOpen && <LookPicker value={look} director={director} onCancel={() => setLookOpen(false)} onSave={saveLook} />}
      {exporting && <ExportSheet dir={project.dir} projectAspect={project.project.aspect_ratio} shots={shots.length}
                                 rendered={shots.filter((s) => latest.get(s.id)?.state === "ready").length}
                                 onClose={() => setExporting(false)} />}
      {confirmAll && <ConfirmRender count={toRender.length} seconds={0} provider={defaultProvider(keys)}
                                    model={AUTO_MODEL[defaultProvider(keys)]} onCancel={() => setConfirmAll(false)} onConfirm={renderAll} />}
      {job && (
        <div className="toast glass" role="status">
          <div className="t">{job.title}</div>
          <div className="s">{job.detail}</div>
          <div className="progress indet"><i /></div>
        </div>
      )}
      {error && (
        <div className="toast glass" role="alert" style={{ borderColor: "rgba(239,107,115,0.4)" }}>
          <div className="t" style={{ color: "var(--error)" }}>Direction stopped</div>
          <div className="s">{error}</div>
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
            <button className="btn" onClick={() => setError("")}>OK</button></div>
        </div>
      )}
    </div>
  );
}

const aspectNum = (r?: string) => {
  const m = r?.match(/^([\d.]+):([\d.]+)$/);
  return m ? String(Number(m[1]) / Number(m[2])) : String(16 / 9);
};
const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function RailBtn({ icon, label, active, disabled, onClick, badge }: {
  icon: React.ReactNode; label: string; active?: boolean; disabled?: boolean; onClick?: () => void; badge?: number;
}) {
  return <button className={active ? "active" : ""} disabled={disabled} onClick={onClick}
                 title={disabled ? `${label} — coming soon` : label} aria-current={active ? "page" : undefined}>
    {icon}<span>{label}</span>{badge ? <i className="rail-badge" aria-label={`${badge} need attention`}>{badge}</i> : null}</button>;
}

export function StateChip({ shot }: { shot: Shot }) {
  if (shot.flags?.length) return <span className="chip review"><I.Alert size={12} /> Needs review</span>;
  const s = shot.state ?? "planned";
  if (s === "ready") return <span className="chip ready"><I.Check size={12} /> Ready</span>;
  if (s === "locked") return <span className="chip"><I.Lock size={12} /> Locked</span>;
  if (s === "failed") return <span className="chip failed"><I.Alert size={12} /> Failed</span>;
  return <span className="chip planned"><I.Circle size={12} /> Planned</span>;
}

/** A rendered take, kept in step with the master audio (the song is the clock). */
function Clip({ src, offset, playing }: { src: string; offset: number; playing: boolean }) {
  const v = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const el = v.current;
    if (!el) return;
    if (Math.abs(el.currentTime - offset) > 0.15) el.currentTime = Math.max(0, offset);
    if (playing && el.paused) el.play().catch(() => {});
    if (!playing && !el.paused) el.pause();
  }, [offset, playing, src]);
  return <video ref={v} className="clip" src={src} muted playsInline preload="auto" />;
}

function Storyboard({ shot, scene, job, hidden }: { shot: Shot; scene?: Scene; job?: Job; hidden?: boolean }) {
  const text = shot.visual_prompt ?? shot.beats.join(" ");
  return (
    <>
      <div className="frame-info">
        <span className="chip num">{shot.id}</span>
        {job ? <JobChip job={job} /> : <StateChip shot={shot} />}
        <span className="chip num">{(shot.end - shot.start).toFixed(1)}s</span>
      </div>
      {!hidden && <div className="board">
        {scene && <div className="scene-head">{scene.heading}</div>}
        <div className="desc">{text}</div>
        <div className="framing">{[shot.framing, shot.camera_movement ?? shot.camera_moves?.join(", ")].filter(Boolean).join(" · ")}</div>
      </div>}
    </>
  );
}

// ---------------- inspector ----------------

function Inspector({ sel, shots, scenes, map, plan, director, project, onClose, renderPanel, lookLabel, onLook }: {
  sel: Selection; shots: Shot[]; scenes: Scene[]; map: SongMap | null; plan: Plan | null; director: boolean;
  project: LoadedProject; onClose: () => void; renderPanel: (s: Shot) => React.ReactNode; lookLabel: string; onLook: () => void;
}) {
  if (sel?.kind === "shot") {
    const s = shots.find((x) => x.id === sel.id);
    if (s) return <ShotInspector shot={s} scene={scenes.find((c) => c.number === s.scene)} director={director} onClose={onClose}
                                 renderPanel={renderPanel(s)} />;
  }
  if (sel?.kind === "section" && map) {
    const sec = map.sections[sel.index];
    const lines = map.lyrics.filter((l) => l.start != null && l.start >= sec.start && l.start < sec.end);
    return (
      <>
        <div className="inspector-head"><span className="t">{sec.group || sec.label}</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><I.Close size={18} /></button></div>
        <div className="inspector-body">
          <div className="insp-section"><div className="kv">
            <span className="k">Time</span><span className="v num">{fmtTime(sec.start)} – {fmtTime(sec.end)}</span>
            <span className="k">Mood</span><span className="v">{sec.mood}</span>
            <span className="k">Energy</span><span className="v"><Meter v={sec.energy} /></span>
          </div></div>
          {lines.length > 0 && <div className="insp-section"><h4>Lyrics</h4>{lines.map((l, i) => <p key={i} className="lyric-q">{l.text}</p>)}</div>}
        </div>
      </>
    );
  }
  return (
    <>
      <div className="inspector-head"><span className="t">Project</span></div>
      <div className="inspector-body">
        <div className="insp-section"><div className="kv">
          <span className="k">Title</span><span className="v">{project.project.title}</span>
          {map && <><span className="k">Tempo</span><span className="v num">{map.bpm.toFixed(1)} BPM</span>
            <span className="k">Length</span><span className="v num">{fmtTime(map.duration)}</span>
            <span className="k">Sections</span><span className="v num">{map.sections.length}</span>
            {map.lyric_match != null && <><span className="k">Lyrics heard</span><span className="v num">{Math.round(map.lyric_match * 100)}%</span></>}</>}
          <span className="k">Shots</span><span className="v num">{shots.length}</span>
          <span className="k">Renderer</span><span className="v">Auto</span>
        </div></div>
        <div className="insp-section look-row">
          <h4>Look</h4>
          <div className="file-row"><span className="name">{lookLabel}</span><button className="btn ghost small" onClick={onLook}>Change</button></div>
        </div>
        {plan?.meta?.LOGLINE && <div className="insp-section"><h4>Story</h4><p className="prose">{plan.meta.LOGLINE}</p></div>}
        {plan?.meta?.["VISUAL STYLE"] && <div className="insp-section"><h4>Look</h4><p className="prose">{plan.meta["VISUAL STYLE"]}</p></div>}
        {plan?.characters?.length ? <div className="insp-section"><h4>Cast</h4>
          {plan.characters.map((c) => <p key={c.name} className="prose"><b style={{ color: "var(--frost)" }}>{c.name}</b> — {c.archetype}</p>)}</div> : null}
        {director && scenes.some((s) => s.director_note) && <div className="insp-section"><h4>Director notes</h4>
          {scenes.filter((s) => s.director_note).map((s) => <p key={s.number} className="prose" style={{ marginBottom: 8 }}>
            <b style={{ color: "var(--frost)" }}>Scene {s.number}.</b> {s.director_note}</p>)}</div>}
      </div>
    </>
  );
}

function ShotInspector({ shot: s, scene, director, onClose, renderPanel }: {
  shot: Shot; scene?: Scene; director: boolean; onClose: () => void; renderPanel: React.ReactNode;
}) {
  const row = (k: string, v?: string | number | null) => (v === undefined || v === null || v === "" ? null :
    <><span className="k">{k}</span><span className="v">{v}</span></>);
  return (
    <>
      <div className="inspector-head"><span className="t num">Shot {s.id}</span>
        <button className="icon-btn" onClick={onClose} aria-label="Close"><I.Close size={18} /></button></div>
      <div className="inspector-body">
        <div className="insp-section" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <StateChip shot={s} /><span className="chip">Renderer: Auto</span>
        </div>
        {s.flags?.map((f) => <div key={f} className="flag"><I.Alert size={14} /> {f}</div>)}
        <div className="insp-section"><div className="kv">
          {row("Time", `${fmtTime(s.start)} → ${fmtTime(s.end)}`)}
          {row("Duration", `${(s.end - s.start).toFixed(2)} s`)}
          {row("Section", s.section)}
          {row("Performers", s.performers.join(", ") || "—")}
          {row("Emotion", s.emotion)}
          {s.performance_intensity != null && <><span className="k">Intensity</span><span className="v"><Meter v={s.performance_intensity} /></span></>}
        </div></div>
        {renderPanel}
        {s.purpose && <div className="insp-section"><h4>Purpose</h4><p className="prose">{s.purpose}</p></div>}
        <div className="insp-section"><h4>{s.beats.length > 1 ? `Story beats (${s.beats.length})` : "Action"}</h4>
          {s.beats.length > 1 ? <ol className="beats">{s.beats.map((b, i) => <li key={i}>{b}</li>)}</ol> : <p className="prose">{s.beats[0]}</p>}</div>
        {s.lyrics?.length ? <div className="insp-section"><h4>Lyrics under this shot</h4>{s.lyrics.map((l, i) => <p key={i} className="lyric-q">{l}</p>)}</div> : null}
        <div className="insp-section"><h4>Camera</h4><div className="kv">
          {row("Framing", s.framing)}{row("Lens", s.lens)}{row("Movement", s.camera_movement ?? s.camera_moves?.join(", "))}{row("Energy", s.camera_energy)}
        </div></div>
        {(s.performance || s.expression || s.movement) && <div className="insp-section"><h4>Performance</h4><div className="kv">
          {row("Acting", s.performance)}{row("Expression", s.expression)}{row("Movement", s.movement)}</div></div>}
        {director && <>
          {(s.lighting || s.environment || s.wardrobe || s.continuity) && <div className="insp-section"><h4>Look & continuity</h4><div className="kv">
            {row("Lighting", s.lighting)}{row("Set", s.environment)}{row("Wardrobe", s.wardrobe)}{row("Continuity", s.continuity)}{row("Sync", s.sync_event)}</div></div>}
          {s.visual_prompt && <div className="insp-section"><h4>Visual description</h4><p className="prose">{s.visual_prompt}</p></div>}
          {s.dropped_beats?.length ? <div className="insp-section"><h4>Dropped beats</h4><ul className="beats">{s.dropped_beats.map((b, i) => <li key={i}>{b}</li>)}</ul></div> : null}
          <div className="insp-section"><h4>Script source</h4><p className="prose num">{s.source_shots.join(", ")}</p></div>
          {scene && <div className="insp-section"><h4>Scene notes</h4><div className="kv">
            {Object.entries(scene.notes).map(([k, v]) => <Fragment key={k}><span className="k">{k.split("/")[0].toLowerCase().replace(/^\w/, (c) => c.toUpperCase())}</span><span className="v">{v}</span></Fragment>)}</div></div>}
        </>}
        {!director && <p className="prose" style={{ fontSize: 12.5, color: "var(--smoke)" }}>Switch to Director Mode to see lighting, wardrobe, continuity and every scene note.</p>}
      </div>
    </>
  );
}

const Meter = ({ v }: { v: number }) => <span className="meter" aria-label={`${v} of 10`}>{Array.from({ length: 10 }, (_, i) => <i key={i} className={i < v ? "on" : ""} />)}</span>;

// ---------------- timeline ----------------

function Timeline({ map, shots, time, sel, flagged, latest, onSeek, onSelect }: {
  map: SongMap | null; shots: Shot[]; time: number; sel: Selection; flagged: number; latest: Map<string, Job>;
  onSeek: (t: number) => void; onSelect: (s: Selection) => void;
}) {
  const scroll = useRef<HTMLDivElement>(null);
  const wave = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(1200);
  const pps = 24; // pixels per second — whole song is scrollable, shots stay legible
  const dur = map?.duration ?? 0;
  const inner = Math.max(width, dur * pps);
  const x = (t: number) => t * pps;

  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    if (scroll.current) ro.observe(scroll.current);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const c = wave.current;
    if (!c || !map) return;
    const dpr = window.devicePixelRatio || 1;
    const W = dur * pps, H = 54;
    c.width = W * dpr; c.height = H * dpr; c.style.width = `${W}px`; c.style.height = `${H}px`;
    const g = c.getContext("2d")!;
    g.scale(dpr, dpr);
    const p = map.peaks ?? [];
    const bw = W / Math.max(1, p.length);
    g.fillStyle = "rgba(232,180,92,0.5)";
    p.forEach((v, i) => { const h = Math.max(0.5, v * (H / 2 - 2)); g.fillRect(i * bw, H / 2 - h, Math.max(1, bw - 0.3), h * 2); });
    g.fillStyle = "rgba(244,247,250,0.10)";
    for (const d of map.downbeats) g.fillRect(x(d), 0, 1, H);
    g.fillStyle = "#E8B45C";
    for (const a of map.accents) g.fillRect(x(a) - 1, H - 5, 3, 3);
  }, [map, dur]);

  // keep the playhead in view while playing
  useEffect(() => {
    const s = scroll.current;
    if (!s) return;
    const px = x(time);
    if (px < s.scrollLeft + 40 || px > s.scrollLeft + s.clientWidth - 80) s.scrollLeft = Math.max(0, px - s.clientWidth * 0.3);
  }, [time]);

  const clickSeek = (e: React.MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    onSeek((e.clientX - r.left) / pps);
  };

  if (!map) return <section className="timeline"><div className="tl-head">No song map yet.</div></section>;
  return (
    <section className="timeline" aria-label="Timeline">
      <div className="tl-head">
        <span>Song Map</span>
        <div className="legend">
          <span><i className="dot" style={{ background: "var(--gold)" }} /> Music</span>
          <span><i className="dot" style={{ background: "var(--signal)" }} /> Playhead</span>
        </div>
        <div style={{ flex: 1 }} />
        {flagged > 0 && <span style={{ color: "var(--warning)", display: "flex", gap: 6, alignItems: "center" }}><I.Alert size={14} /> {flagged} shots may need attention</span>}
      </div>
      <div className="tl-scroll" ref={scroll}>
        <div className="tl-inner" style={{ width: inner }} onClick={clickSeek}>
          <div className="tl-sections">
            {map.sections.map((s, i) => (
              <div key={i} className="tl-section" style={{ left: x(s.start), width: x(s.end - s.start) - 2 }}
                   onClick={(e) => { e.stopPropagation(); onSelect({ kind: "section", index: i }); onSeek(s.start); }}>
                {(s.group && s.group.length > 2 ? s.group : s.label).toUpperCase()}</div>
            ))}
          </div>
          <canvas className="tl-wave" ref={wave} />
          <div className="tl-lyrics">
            {map.lyrics.filter((l) => l.start != null).map((l, i) => (
              <div key={i} className="tl-lyric" title={l.text} style={{ left: x(l.start!), width: Math.max(18, x((l.end ?? l.start!) - l.start!)) }}>{l.text}</div>
            ))}
          </div>
          <div className="tl-shots">
            {shots.map((s) => (
              <div key={s.id} className={`shot-card ${sel?.kind === "shot" && sel.id === s.id ? "sel" : ""} ${s.flags?.length ? "flagged" : ""}`}
                   style={{ left: x(s.start) + 1, width: Math.max(8, x(s.end - s.start) - 3) }}
                   title={`${s.id} · ${s.framing}`}
                   onClick={(e) => { e.stopPropagation(); onSelect({ kind: "shot", id: s.id }); }}>
                <div className="id num">{s.id.slice(1)}</div>
                <div className="fr">{s.framing}</div>
                <div className="st"><CardState job={latest.get(s.id)} flagged={!!s.flags?.length} /></div>
              </div>
            ))}
          </div>
          <div className="playhead" style={{ left: x(time) }} />
        </div>
      </div>
    </section>
  );
}

function CardState({ job, flagged }: { job?: Job; flagged: boolean }) {
  if (needsAttention(job)) return <span style={{ color: "var(--warning)" }}><I.Alert size={10} /> Needs review</span>;
  if (job?.state === "ready") return <span style={{ color: "var(--success)" }}><I.Check size={10} /> Ready</span>;
  if (job && ACTIVE_STATES.includes(job.state)) return <span style={{ color: "var(--signal-bright)" }}><span className="spin sm" /> {job.state === "queued" ? "Queued" : "Rendering"}</span>;
  if (job?.state === "failed") return <span style={{ color: "var(--error)" }}><I.Alert size={10} /> Failed</span>;
  if (job?.state === "uncertain") return <span style={{ color: "var(--warning)" }}><I.Alert size={10} /> Check</span>;
  if (flagged) return <><I.Alert size={10} /> Review</>;
  return <><I.Circle size={10} /> Planned</>;
}
