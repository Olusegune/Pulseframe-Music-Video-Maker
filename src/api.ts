import { invoke, convertFileSrc } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type Section = { start: number; end: number; label: string; group: string; energy: number; mood: string };
export type LyricLine = { section: string; text: string; start: number | null; end: number | null };
export type SongMap = {
  duration: number; bpm: number; beats: number[]; downbeats: number[];
  energy_curve: [number, number][]; accents: number[]; sections: Section[];
  lyrics: LyricLine[]; lyric_match: number | null; peaks: number[]; analyzer: string;
};

/** A shot as shown in the studio: planned (script import) or directed (Director Engine). */
export type Shot = {
  id: string; scene: number; number: number; start: number; end: number;
  beats: string[]; source_shots: string[]; performers: string[];
  framing: string; state: string; renderer: string;
  description?: string; camera_moves?: string[]; lyrics?: string[]; section?: string;
  flags?: string[]; sync_accents?: number[];
  // directed-only
  purpose?: string; emotion?: string; performance_intensity?: number; performance?: string;
  expression?: string; movement?: string; lens?: string; camera_movement?: string; camera_energy?: string;
  lighting?: string; environment?: string; wardrobe?: string; continuity?: string; sync_event?: string;
  visual_prompt?: string; dropped_beats?: string[]; revised?: number;
};
export type Scene = {
  number: number; heading: string; start: number; end: number; notes: Record<string, string>;
  fields?: Record<string, string>; characters?: string[]; shots: Shot[];
  director_note?: string; issues?: string[];
};
export type Character = { name: string; archetype: string; appearance: string; motivation: string; acting_notes: string };
export type Plan = { meta: Record<string, string>; characters: Character[]; scenes: Scene[]; model?: string };

export type ProjectSummary = { dir: string; title: string; state: string; modified: number; song: string };
export type LoadedProject = {
  dir: string;
  project: { title: string; state: string; song: string; lyrics?: string; script?: string; aspect_ratio?: string; artist?: string; look?: Look | string;
    quality?: ProjectSettings["quality"]; lip_sync?: ProjectSettings["lip_sync"] };
  song_path: string | null;
  song_map: SongMap | null;
  production: Plan | null;
  directed: Plan | null;
  jobs: Job[];
  doc?: string | null;
  keyframes?: Record<string, Record<string, string>>;
  concepts?: { concepts: Concept[]; model?: string } | null;
  treatment?: { concept: Concept; notes?: string } | null;
};
export type Concept = {
  title: string; premise: string; mood: string; performance_approach: string; cinematic_style: string; palette: string[];
  environment: string; wardrobe: string; movement: string; narrative_level: "performance" | "hybrid" | "narrative";
  hero_frame: string; suggested_look: string;
};
export type JobState = "queued" | "submitting" | "submitted" | "ready" | "failed" | "uncertain" | "dismissed";
export type Job = {
  id: string; shot_id: string; plan: string; provider: "fal" | "kie" | "google"; model: string; state: JobState; kind?: "video" | "image" | "lipsync"; source_job?: string | null;
  overrides: Record<string, unknown>; payload?: Record<string, unknown>; provider_job_id: string | null;
  output: string | null; error: string | null; cost: number | null; cost_unit?: string | null;
  created: number; updated: number; attempts: number; shot_start: number; shot_end: number; look?: string;
  fix_notes?: string[]; review?: Review;
};
export type ProjectSettings = { aspect_ratio: string; quality: "draft" | "standard" | "high" | "max"; lip_sync: "auto" | "closeups" | "off" };
export type Estimate = { provider: string; model: string; shots: number; usd: number | null; usd_known: number;
  unknown: number; basis: string; kie_credits?: number; lipsync_shots?: number };
export type ReviewIssue = { kind: string; severity: "minor" | "major"; detail: string; fix: string };
export type Review = {
  reviewed: boolean; status?: "good" | "minor" | "needs_attention"; summary?: string; issues?: ReviewIssue[];
  fixes?: string[]; visual?: { model: string } | null; visual_error?: string; accepted?: boolean; error?: string;
};
export type ManifestInput = {
  name: string; type: string; items: string | null; enum: (string | number)[] | null; default: unknown; max_length?: number | null;
  minimum: number | null; maximum: number | null; max_items: number | null; description: string; required: boolean;
};
export type Manifest = {
  provider: string; model: string; title: string; category: string; inputs: ManifestInput[];
  roles: Record<string, string>; ref_syntax: string | null;
};
export type CatalogItem = { provider: string; model: string; title: string; category: string };
export const AUTO_MODEL: Record<string, string> = {
  fal: "bytedance/seedance-2.0/reference-to-video",
  kie: "bytedance/seedance-2",
  google: "veo-3.1-fast-generate-preview",
};
export const AUTO_LIPSYNC_MODEL: Record<string, string> = { fal: "fal-ai/sync-lipsync/v3", kie: "volcengine/video-to-video-lip-sync" };
export const AUTO_IMAGE_MODEL: Record<string, string> = {
  fal: "fal-ai/nano-banana/edit",
  kie: "google/nano-banana-edit",
  google: "gemini-3.1-flash-image",
};

export type Style = { id: string; name: string; group: string; description: string; prompt: string; avoid: string; fit?: string };
export type Look = { style: string; notes?: string; prompt?: string; avoid?: string };

export type ExportResult = {
  path: string; preset: string; width: number; height: number; fps: number; duration: number;
  shots: number; rendered: number; draft: boolean;
};

export type KeyStatus = { openai: boolean; fal: boolean; kie: boolean; google: boolean };
export type EngineEvent = { task: string; event: string; job?: unknown; stage?: string; progress?: number; message?: string; [k: string]: unknown };

export const api = {
  appReady: () => invoke<void>("app_ready"),
  engineStatus: () => invoke<{ ready: boolean; dev: boolean; gpu: boolean }>("engine_status"),
  setupEngine: () => invoke<{ ready: boolean }>("setup_engine"),
  setProjectSettings: (dir: string, settings: Partial<ProjectSettings>) => invoke<void>("set_project_settings", { dir, settings }),
  importReference: (dir: string, path: string) =>
    invoke<{ ref: string; kind: string; name: string; path: string }>("import_reference", { dir, path }),
  creativeDirections: (dir: string, notes = "") => invoke<{ concepts: Concept[] }>("creative_directions", { dir, notes }),
  writeTreatment: (dir: string, index: number, notes = "") =>
    invoke<{ scenes: number; shots: number; title: string }>("write_treatment", { dir, index, notes }),
  directorCommand: (dir: string, note: string, selected: string | null, playhead: number | null) =>
    invoke<{ id: string | null; summary: string; not_done: string; changed: string[] }>("director_command", { dir, note, selected, playhead }),
  undoCommand: (dir: string, id: string) => invoke<{ id: string; restored: string[] }>("undo_command", { dir, id }),
  saveProject: (dir: string) => invoke<{ saved: number }>("save_project", { dir }),
  saveProjectAs: (dir: string, dest: string) => invoke<string>("save_project_as", { dir, dest }),
  launchPath: () => invoke<string | null>("launch_path"),
  onMenu: (fn: (id: string) => void): Promise<UnlistenFn> => listen<string>("menu", (e) => fn(e.payload)),
  onOpenPath: (fn: (path: string) => void): Promise<UnlistenFn> => listen<string>("open-path", (e) => fn(e.payload)),
  keyStatus: () => invoke<KeyStatus>("key_status"),
  readText: (path: string) => invoke<string>("read_text", { path }),
  setKey: (provider: string, key: string) => invoke<void>("set_key", { provider, key }),
  deleteKey: (provider: string) => invoke<void>("delete_key", { provider }),
  listProjects: () => invoke<ProjectSummary[]>("list_projects"),
  createProject: (songPath: string, title: string, lyrics: string | null, scriptPath: string | null, look: Look | null) =>
    invoke<string>("create_project", { songPath, title, lyrics, scriptPath, look }),
  listStyles: () => invoke<Style[]>("list_styles"),
  setLook: (dir: string, look: Look) => invoke<void>("set_look", { dir, look }),
  loadProject: (dir: string) => invoke<LoadedProject>("load_project", { dir }),
  analyzeProject: (dir: string) => invoke<void>("analyze_project", { dir }),
  directProject: (dir: string) => invoke<void>("direct_project", { dir }),
  ensureRenderer: (dir: string) => invoke<void>("ensure_renderer", { dir }),
  renderCatalog: (provider: string, kind: "video" | "image" | "lipsync" = "video") => invoke<CatalogItem[]>("render_catalog", { provider, kind }),
  setKeyframe: (dir: string, plan: string, shot: string, image: string | null) => invoke<void>("set_keyframe", { dir, plan, shot, image }),
  modelManifest: (provider: string, model: string) => invoke<Manifest>("model_manifest", { provider, model }),
  renderPreview: (dir: string, shot: string, provider: string, model: string | null, overrides: Record<string, unknown>,
                  kind: "video" | "image" = "video") =>
    invoke<{ manifest: Manifest; payload: Record<string, unknown>; lip_sync?: boolean; singing?: { performer: string; lyrics: string[] } | null }>("render_preview", { dir, shot, provider, model, overrides, kind }),
  queueRender: (dir: string, shots: string[], provider: string, model: string | null, overrides: Record<string, unknown>,
                fixNotes: string[] = [], kind: "video" | "image" | "lipsync" = "video", sourceJob: string | null = null) =>
    invoke<Job[]>("queue_render", { dir, shots, provider, model, overrides, fixNotes, kind, sourceJob }),
  renderEstimate: (dir: string, shots: string[], provider: string, model: string | null, kind: "video" | "image" = "video") =>
    invoke<Estimate>("render_estimate", { dir, shots, provider, model, kind }),
  resolveJob: (dir: string, job: string, action: "retry" | "dismiss" | "accept") => invoke<Job>("resolve_job", { dir, job, action }),
  onRenderIdle: (fn: (e: { dir: string; error: string | null }) => void): Promise<UnlistenFn> =>
    listen<{ dir: string; error: string | null }>("render-idle", (e) => fn(e.payload)),
  exportProject: (dir: string, preset: string) => invoke<ExportResult>("export_project", { dir, preset }),
  onEngine: (fn: (e: EngineEvent) => void): Promise<UnlistenFn> => listen<EngineEvent>("engine-progress", (e) => fn(e.payload)),
  mediaUrl: (path: string) => ((window as unknown as { __PF_MOCK__?: boolean }).__PF_MOCK__ ? path : convertFileSrc(path)),
};

export const fmtTime = (t: number) => {
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(2).padStart(5, "0")}`;
};

export const errorText = (e: unknown) => (typeof e === "string" ? e : e instanceof Error ? e.message : "Something went wrong.");
