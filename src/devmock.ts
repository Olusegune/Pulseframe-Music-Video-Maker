// Browser-only UI preview (`?mock`): answers the app's backend calls with local sample data so the
// screens can be checked outside the desktop shell. Never active inside the Tauri app.
import { mockIPC, mockWindows } from "@tauri-apps/api/mocks";

export async function installMock() {
  // Sample data lives outside public/ so it never ships in the app bundle.
  const url = (f: string) => new URL(`../mock-data/${f}`, import.meta.url).href;
  const [song_map, production, preview] = await Promise.all(["songmap.json", "production.json", "preview.json"].map((n) => fetch(url(n)).then((r) => r.json())));
  const now = Date.now() / 1000;
  const jobs = [
    { id: "j1", shot_id: "S01-01", plan: "production", provider: "fal", model: preview.manifest.model, state: "submitted", overrides: {}, provider_job_id: "r1", output: null, error: null, cost: null, created: now, updated: now, attempts: 1, shot_start: 0, shot_end: 2 },
    { id: "j2", shot_id: "S01-02", plan: "production", provider: "fal", model: preview.manifest.model, state: "failed", overrides: {}, provider_job_id: "r2", output: null, error: "422: Prompt was flagged by the provider's content filter.", cost: null, created: now, updated: now, attempts: 1, shot_start: 2, shot_end: 4.5 },
    { id: "j3", shot_id: "S01-03", plan: "production", provider: "kie", model: "bytedance/seedance-2", state: "uncertain", overrides: {}, provider_job_id: null, output: null, error: "The app closed while this shot was being sent. It may already be rendering (and billed). Check your provider dashboard before retrying.", cost: null, created: now, updated: now, attempts: 1, shot_start: 4.5, shot_end: 6.5 },
  ];
  const project = { title: "Exit Plan", state: "analyzed", song: "song.wav", aspect_ratio: "2.39:1", artist: "Uncle Sege" };
  mockWindows("main");
  mockIPC((cmd) => {
    switch (cmd) {
      case "list_projects": return [{ dir: "mock", title: "Exit Plan", state: "analyzed", modified: Date.now() / 1000, song: "song.wav" }];
      case "load_project": return { dir: "mock", project, song_path: url("song.wav"), song_map, production, directed: null, jobs };
      case "key_status": return { openai: false, fal: true, kie: false };
      case "render_preview": return preview;
      case "render_catalog": return [{ provider: "fal", model: preview.manifest.model, title: preview.manifest.title, category: "image-to-video" }];
      case "queue_render": return [];
      case "export_project": return new Promise((r) => setTimeout(() => r({ path: "C:\Users\you\Documents\PULSEFRAME\Exit Plan.pulseframe\exports\Exit Plan - Cinema (draft).mp4", preset: "Cinema 2.39:1", width: 1920, height: 804, fps: 24, duration: 191.44, shots: 70, rendered: 2, draft: true }), 800));
      case "plugin:event|listen": return 1;
      default: return null;
    }
  });
  (window as unknown as { __PF_MOCK__: boolean }).__PF_MOCK__ = true;
}
