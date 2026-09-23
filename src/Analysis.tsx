import { useEffect, useRef, useState } from "react";
import { api, errorText, type EngineEvent, type LyricLine, type Section } from "./api";

type Partial = {
  duration?: number; peaks?: number[]; beats?: number[]; energy?: [number, number][];
  sections?: Section[]; lyrics?: LyricLine[];
};

const STAGES: Record<string, string> = {
  loading: "Listening…", waveform: "Hearing the shape of the song", beats: "Finding the pulse",
  energy: "Feeling the energy", accents: "Marking the big moments", sections: "Understanding the structure",
  vocals: "Isolating the voice", lyrics: "Following the lyrics", script: "Reading your script",
};

/** PRD §49: the waveform draws, sections emerge, lyrics appear, beats form — then "I understand the song." */
export function Analysis({ dir, title, onDone, onBack }: {
  dir: string; title: string; onDone: () => void; onBack: () => void;
}) {
  const [data, setData] = useState<Partial>({});
  const [stage, setStage] = useState("Listening…");
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const canvas = useRef<HTMLCanvasElement>(null);
  const started = useRef(false);
  const born = useRef(performance.now());

  useEffect(() => {
    const un = api.onEngine((e: EngineEvent) => {
      if (e.stage && STAGES[e.stage]) setStage(STAGES[e.stage]);
      setData((d) => {
        const n = { ...d };
        if (e.stage === "waveform") { n.duration = e.duration as number; n.peaks = e.peaks as number[]; born.current = performance.now(); }
        if (e.stage === "beats") n.beats = e.beats as number[];
        if (e.stage === "energy") n.energy = e.energy_curve as [number, number][];
        if (e.stage === "sections") n.sections = e.sections as Section[];
        if (e.lyrics) n.lyrics = e.lyrics as LyricLine[];
        return n;
      });
    });
    if (!started.current) {
      started.current = true;
      api.analyzeProject(dir)
        .then(() => { setDone(true); setStage(""); })
        .catch((e) => setError(errorText(e)));
    }
    return () => { un.then((f) => f()); };
  }, [dir]);

  // Continuous redraw so each layer can ease in as it arrives.
  useEffect(() => {
    let raf = 0;
    const draw = () => {
      const c = canvas.current;
      if (c && data.duration) paint(c, data, (performance.now() - born.current) / 1400);
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [data]);

  return (
    <div className="reveal">
      <div className={`reveal-title ${done ? "done" : ""}`}>{done ? "I understand the song." : title}</div>
      <div className="reveal-map"><canvas ref={canvas} /></div>
      {error ? (
        <div style={{ textAlign: "center" }}>
          <div className="error-text">Analysis stopped: {error}</div>
          <button className="btn" style={{ marginTop: 14 }} onClick={onBack}>Back to Home</button>
        </div>
      ) : done ? (
        <button className="btn hero" onClick={onDone}>Enter the Studio</button>
      ) : (
        <div className="reveal-stage">{stage}</div>
      )}
    </div>
  );
}

function paint(c: HTMLCanvasElement, d: Partial, reveal: number) {
  const dpr = window.devicePixelRatio || 1;
  const W = c.clientWidth, H = c.clientHeight;
  if (c.width !== W * dpr) { c.width = W * dpr; c.height = H * dpr; }
  const g = c.getContext("2d")!;
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, W, H);
  const dur = d.duration!;
  const x = (t: number) => (t / dur) * W;
  const mid = 96, amp = 50;
  const shown = Math.min(1, reveal);

  // waveform draws left → right
  const peaks = d.peaks ?? [];
  g.fillStyle = "rgba(232,180,92,0.55)";
  const n = Math.floor(peaks.length * shown);
  const bw = W / Math.max(1, peaks.length);
  for (let i = 0; i < n; i++) {
    const h = Math.max(1, peaks[i] * amp);
    g.fillRect(i * bw, mid - h, Math.max(1, bw - 0.4), h * 2);
  }
  // energy curve glows
  if (d.energy?.length) {
    g.beginPath();
    d.energy.forEach(([t, e], i) => { const px = x(t), py = mid + amp + 26 - e * 60; i ? g.lineTo(px, py) : g.moveTo(px, py); });
    g.strokeStyle = "rgba(100,183,255,0.85)"; g.lineWidth = 1.5;
    g.shadowColor = "rgba(100,183,255,0.6)"; g.shadowBlur = 10; g.stroke(); g.shadowBlur = 0;
  }
  // beats quietly form
  if (d.beats?.length) {
    g.fillStyle = "rgba(244,247,250,0.22)";
    for (const b of d.beats) g.fillRect(x(b), mid + amp + 32, 1, 5);
  }
  // sections emerge
  for (const s of d.sections ?? []) {
    g.fillStyle = "#E8B45C"; g.fillRect(x(s.start), 6, 2, 24);
    g.font = "600 11px 'Segoe UI Variable Text', system-ui"; g.fillText(s.label, x(s.start) + 7, 22);
  }
  // lyrics appear
  g.fillStyle = "rgba(166,175,188,0.9)"; g.font = "11px 'Segoe UI Variable Text', system-ui";
  let lastEnd = -1;
  for (const l of d.lyrics ?? []) {
    if (l.start == null) continue;
    const px = x(l.start);
    if (px < lastEnd + 6) continue;
    const text = l.text.length > 22 ? l.text.slice(0, 21) + "…" : l.text;
    g.fillText(text, px, H - 6);
    lastEnd = px + g.measureText(text).width;
  }
}
