import { useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { api, errorText } from "./api";
import { Mark } from "./icons";

/** First launch of the installed app: set up the private audio/AI engine once, with honest progress. */
export function EngineSetup({ gpu, onReady }: { gpu: boolean; onReady: () => void }) {
  const [step, setStep] = useState<{ step: number; total: number; label: string } | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const started = useRef(false);

  const start = async () => {
    setError(""); setRunning(true);
    try { await api.setupEngine(); onReady(); }
    catch (e) { setError(errorText(e)); setRunning(false); }
  };

  useEffect(() => {
    const un = listen<{ step: number; total: number; label: string }>("engine-setup", (e) => setStep(e.payload));
    if (!started.current) { started.current = true; start(); }
    return () => { un.then((f) => f()); };
  }, []);

  const pct = step ? Math.round(((step.step - 1) / step.total) * 100) : 0;
  return (
    <div className="reveal">
      <div className="wordmark"><Mark size={28} /> PULSEFRAME</div>
      <div className="reveal-title">Getting PULSEFRAME ready</div>
      <p className="sub" style={{ maxWidth: 560, textAlign: "center", color: "var(--mist)" }}>
        One-time setup of the engine that listens to songs, times lyrics and talks to the AI renderers.
        {gpu ? " Your NVIDIA graphics card will be used to make it fast." : ""} This needs an internet connection and
        can take several minutes. You won't need to do it again.
      </p>
      <div style={{ width: "min(520px, 100%)" }}>
        <div className="dim" style={{ marginBottom: 6 }}>{step ? `Step ${step.step} of ${step.total}: ${step.label}` : "Starting…"}</div>
        <div className={`progress ${running ? "indet" : ""}`}><i style={{ width: `${pct}%` }} /></div>
      </div>
      {error && (
        <div style={{ textAlign: "center", maxWidth: 560 }}>
          <div className="error-text">Setup stopped: {error}</div>
          <p className="dim">Check your internet connection and try again. Finished steps are kept.</p>
          <button className="btn primary" onClick={start}>Try again</button>
        </div>
      )}
    </div>
  );
}
