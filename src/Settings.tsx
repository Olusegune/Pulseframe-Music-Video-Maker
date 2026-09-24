import { useEffect, useState } from "react";
import { api, errorText, type KeyStatus } from "./api";
import { Check, Close } from "./icons";

const PROVIDERS: { id: keyof KeyStatus; name: string; purpose: string }[] = [
  { id: "openai", name: "OpenAI", purpose: "Director Engine: treatment, shot planning and direction" },
  { id: "fal", name: "fal.ai", purpose: "Video and image rendering" },
  { id: "kie", name: "Kie.ai", purpose: "Video and image rendering" },
];

/** Keys go straight to the Windows Credential Manager / macOS Keychain; they never touch project files. */
export function Settings({ onClose }: { onClose: () => void }) {
  const [status, setStatus] = useState<KeyStatus>({ openai: false, fal: false, kie: false });
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<Record<string, string>>({});

  const refresh = () => api.keyStatus().then((k) => { setStatus(k); window.dispatchEvent(new Event("pf-keys-changed")); });
  useEffect(() => { refresh(); }, []);

  const save = async (id: string) => {
    try {
      await api.setKey(id, draft[id] ?? "");
      setDraft((d) => ({ ...d, [id]: "" }));
      setMsg((m) => ({ ...m, [id]: "" }));
      refresh();
    } catch (e) { setMsg((m) => ({ ...m, [id]: errorText(e) })); }
  };
  const remove = async (id: string) => { await api.deleteKey(id); refresh(); };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet glass" role="dialog" aria-label="Settings" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
          <div>
            <h2>Connections</h2>
            <p className="sub">Keys are stored securely by Windows, never in your projects.</p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><Close /></button>
        </div>
        {PROVIDERS.map((p) => (
          <div className="field" key={p.id}>
            <label htmlFor={`k-${p.id}`} style={{ display: "flex", justifyContent: "space-between" }}>
              <span>{p.name} <span className="opt">{p.purpose}</span></span>
              {status[p.id] ? <span className="status-ok"><Check size={14} /> Connected</span> : <span className="status-missing">Not connected</span>}
            </label>
            <div className="key-row">
              <input id={`k-${p.id}`} type="password" autoComplete="off" spellCheck={false} className="text-input"
                     placeholder={status[p.id] ? "Replace key…" : "Paste your API key"}
                     value={draft[p.id] ?? ""} onChange={(e) => setDraft((d) => ({ ...d, [p.id]: e.target.value }))}
                     onKeyDown={(e) => e.key === "Enter" && save(p.id)} />
              <button className="btn primary" onClick={() => save(p.id)} disabled={!(draft[p.id] ?? "").trim()}>Save</button>
              {status[p.id] && <button className="btn ghost" onClick={() => remove(p.id)}>Remove</button>}
            </div>
            {msg[p.id] && <div className="error-text">{msg[p.id]}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
