// Browser-only UI preview (`?mock`): answers the app's backend calls with local sample data so the
// screens can be checked outside the desktop shell. Never active inside the Tauri app.
import { mockIPC, mockWindows } from "@tauri-apps/api/mocks";

export async function installMock() {
  const [song_map, production] = await Promise.all(["songmap", "production"].map((n) => fetch(`/mock/${n}.json`).then((r) => r.json())));
  const project = { title: "Exit Plan", state: "analyzed", song: "song.wav", aspect_ratio: "2.39:1", artist: "Uncle Sege" };
  mockWindows("main");
  mockIPC((cmd) => {
    switch (cmd) {
      case "list_projects": return [{ dir: "mock", title: "Exit Plan", state: "analyzed", modified: Date.now() / 1000, song: "song.wav" }];
      case "load_project": return { dir: "mock", project, song_path: "/mock/song.wav", song_map, production, directed: null };
      case "key_status": return { openai: false, fal: false, kie: false };
      case "plugin:event|listen": return 1;
      default: return null;
    }
  });
  (window as unknown as { __PF_MOCK__: boolean }).__PF_MOCK__ = true;
}
