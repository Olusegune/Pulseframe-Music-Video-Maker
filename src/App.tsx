import { useCallback, useState } from "react";
import { api, errorText, type LoadedProject } from "./api";
import { Home } from "./Home";
import { NewProject } from "./NewProject";
import { Analysis } from "./Analysis";
import { Studio } from "./Studio";
import { Settings } from "./Settings";
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

  const openProject = useCallback(async (dir: string) => {
    setError("");
    try {
      const p = await api.loadProject(dir);
      // A project that was never analysed (or was interrupted) resumes at the listening step.
      if (!p.song_map || p.project.state === "new" || p.project.state === "analyzing") setView({ name: "analysis", dir, title: p.project.title });
      else setView({ name: "studio", project: p });
    } catch (e) { setError(errorText(e)); }
  }, []);

  return (
    <>
      {view.name === "home" && <Home onSong={setNewSong} onOpen={openProject} onSettings={() => setSettings(true)} />}
      {view.name === "analysis" && <Analysis dir={view.dir} title={view.title}
                                             onDone={() => openProject(view.dir)} onBack={() => setView({ name: "home" })} />}
      {view.name === "studio" && <Studio project={view.project} onHome={() => setView({ name: "home" })}
                                         onSettings={() => setSettings(true)} onReload={() => openProject(view.project.dir)} />}
      {newSong && <NewProject songPath={newSong} onCancel={() => setNewSong(null)}
                              onCreated={(dir) => { setNewSong(null); setView({ name: "analysis", dir, title: "" }); }} />}
      {settings && <Settings onClose={() => setSettings(false)} />}
      {error && <div className="toast glass" role="alert"><div className="t" style={{ color: "var(--error)" }}>Could not open</div>
        <div className="s">{error}</div><div style={{ textAlign: "right", marginTop: 10 }}><button className="btn" onClick={() => setError("")}>OK</button></div></div>}
    </>
  );
}
