import { useCallback, useEffect, useState } from "react";
import { open as openDialog, save as saveDialog } from "@tauri-apps/plugin-dialog";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { api, errorText, type LoadedProject } from "./api";
import { Home } from "./Home";
import { NewProject } from "./NewProject";
import { Analysis } from "./Analysis";
import { Studio } from "./Studio";
import { Settings } from "./Settings";
import { HelpSheet } from "./Help";
import { EngineSetup } from "./EngineSetup";
import "./styles.css";

type View =
  | { name: "home" }
  | { name: "analysis"; dir: string; title: string }
  | { name: "studio"; project: LoadedProject };

export default function App() {
  const [view, setView] = useState<View>({ name: "home" });
  const [newSong, setNewSong] = useState<string | null>(null);
  const [settings, setSettings] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [help, setHelp] = useState(false);
  const [engine, setEngine] = useState<{ ready: boolean; gpu: boolean } | null>(null);
  useEffect(() => { api.engineStatus().then(setEngine).catch(() => setEngine({ ready: true, gpu: false })); }, []);
  const say = useCallback((t: string) => { setToast(t); setTimeout(() => setToast(""), 1800); }, []);

  // First paint is done: swap the splash window for this one.
  useEffect(() => { api.appReady().catch(() => {}); }, []);

  const openProject = useCallback(async (dir: string) => {
    setError("");
    try {
      const p = await api.loadProject(dir);
      // A project that was never analysed (or was interrupted) resumes at the listening step.
      if (!p.song_map || p.project.state === "new" || p.project.state === "analyzing") setView({ name: "analysis", dir, title: p.project.title });
      else setView({ name: "studio", project: p });
    } catch (e) { setError(errorText(e)); }
  }, []);

  // A project double-clicked in Explorer: at launch, or while the app is already open.
  useEffect(() => {
    api.launchPath().then((p) => { if (p) openProject(p); }).catch(() => {});
    const un = api.onOpenPath((p) => openProject(p));
    return () => { un.then((f) => f()); };
  }, [openProject]);

  const chooseProject = useCallback(async () => {
    const f = await openDialog({ filters: [{ name: "PULSEFRAME Project", extensions: ["pulseframe"] }] });
    if (typeof f === "string") openProject(f);
  }, [openProject]);

  // Standard File menu (native menu bar + shortcuts).
  const current = view.name === "studio" ? view.project : null;
  useEffect(() => {
    const un = api.onMenu(async (id) => {
      try {
        switch (id) {
          case "new": {
            const f = await openDialog({ filters: [{ name: "Music", extensions: ["mp3", "wav", "m4a"] }] });
            if (typeof f === "string") setNewSong(f);
            break;
          }
          case "open": await chooseProject(); break;
          case "settings": setSettings(true); break;
          case "help": setHelp(true); break;
          case "save":
            if (current) { await api.saveProject(current.dir); say("Saved"); } else say("Open a project to save it.");
            break;
          case "save_as": {
            if (!current) { say("Open a project first."); break; }
            const dest = await saveDialog({ defaultPath: `${current.project.title} copy.pulseframe`,
                                            filters: [{ name: "PULSEFRAME Project", extensions: ["pulseframe"] }] });
            if (dest) { const dir = await api.saveProjectAs(current.dir, dest); await openProject(dir); say("Saved a copy"); }
            break;
          }
          case "reveal": if (current) await revealItemInDir(current.doc ?? current.dir); break;
          case "close": setView({ name: "home" }); break;
          default: window.dispatchEvent(new CustomEvent("pf-menu", { detail: id })); // studio-level items
        }
      } catch (e) { setError(errorText(e)); }
    });
    return () => { un.then((f) => f()); };
  }, [current, chooseProject, openProject, say]);

  return (
    <>
      {engine && !engine.ready && <EngineSetup gpu={engine.gpu} onReady={() => setEngine({ ...engine, ready: true })} />}
      {(!engine || engine.ready) && view.name === "home" && <Home onSong={setNewSong} onOpen={openProject} onChooseProject={chooseProject} onSettings={() => setSettings(true)} onHelp={() => setHelp(true)} />}
      {toast && <div className="toast glass mini" role="status">{toast}</div>}
      {view.name === "analysis" && <Analysis dir={view.dir} title={view.title}
                                             onDone={() => openProject(view.dir)} onBack={() => setView({ name: "home" })} />}
      {view.name === "studio" && <Studio project={view.project} onHome={() => setView({ name: "home" })}
                                         onSettings={() => setSettings(true)} onReload={() => openProject(view.project.dir)} />}
      {newSong && <NewProject songPath={newSong} onCancel={() => setNewSong(null)}
                              onCreated={(dir) => { setNewSong(null); setView({ name: "analysis", dir, title: "" }); }} />}
      {settings && <Settings onClose={() => setSettings(false)} />}
      {help && <HelpSheet onClose={() => setHelp(false)} />}
      {error && <div className="toast glass" role="alert"><div className="t" style={{ color: "var(--error)" }}>Could not open</div>
        <div className="s">{error}</div><div style={{ textAlign: "right", marginTop: 10 }}><button className="btn" onClick={() => setError("")}>OK</button></div></div>}
    </>
  );
}
