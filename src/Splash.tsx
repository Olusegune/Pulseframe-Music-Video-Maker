import { useEffect, useState } from "react";
import splash from "./assets/splash.jpg";

const HOLD_MS = 1800;
const FADE_MS = 500;

/** Launch splash (PRD §39: the brand gradient belongs here). Click or any key skips it. */
export function Splash({ onDone }: { onDone: () => void }) {
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const leave = () => setLeaving(true);
    const t = setTimeout(leave, reduced ? 700 : HOLD_MS);
    window.addEventListener("keydown", leave, { once: true });
    return () => { clearTimeout(t); window.removeEventListener("keydown", leave); };
  }, []);

  useEffect(() => {
    if (!leaving) return;
    const t = setTimeout(onDone, FADE_MS);
    return () => clearTimeout(t);
  }, [leaving, onDone]);

  return (
    <div className={`splash ${leaving ? "leaving" : ""}`} onClick={() => setLeaving(true)} role="img"
         aria-label="PULSEFRAME. Direct music into motion.">
      <img src={splash} alt="" draggable={false} />
    </div>
  );
}
