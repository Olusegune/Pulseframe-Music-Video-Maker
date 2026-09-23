// Geometric, 1.75px stroke, rounded ends (PRD §46). Monochrome; color comes from context.
type P = { size?: number };
const S = ({ size = 20, children }: P & { children: React.ReactNode }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75}
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);

/** PULSEFRAME mark: two waveform strokes inside an open frame (PRD §47). */
export const Mark = ({ size = 22 }: P) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M8 3H4.5A1.5 1.5 0 0 0 3 4.5v15A1.5 1.5 0 0 0 4.5 21H8M16 3h3.5A1.5 1.5 0 0 1 21 4.5v15a1.5 1.5 0 0 1-1.5 1.5H16"
          stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" />
    <path d="M10 8v8M14 5.5v13" stroke="#E8B45C" strokeWidth={2.2} strokeLinecap="round" />
  </svg>
);
export const Home = (p: P) => <S {...p}><path d="M4 11 12 4l8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z" /></S>;
export const Folder = (p: P) => <S {...p}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></S>;
export const Assets = (p: P) => <S {...p}><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></S>;
export const Studio = (p: P) => <S {...p}><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M3 20h18M8 20v-4M16 20v-4" /></S>;
export const Review = (p: P) => <S {...p}><path d="M4 12.5 9 17.5 20 6.5" /></S>;
export const Export = (p: P) => <S {...p}><path d="M12 15V3M7 8l5-5 5 5M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" /></S>;
export const Gear = (p: P) => <S {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 7 19.4a1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 1.2 14H1a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 7a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 9 2.6V2.5a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8 1.7 1.7 0 0 0 1.6 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" /></S>;
export const Note = (p: P) => <S {...p}><path d="M9 18V5l11-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="17" cy="16" r="3" /></S>;
export const Play = (p: P) => <svg width={p.size ?? 18} height={p.size ?? 18} viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15a1 1 0 0 0 1.5.9l12-7.5a1 1 0 0 0 0-1.8l-12-7.5A1 1 0 0 0 7 4.5Z" /></svg>;
export const Pause = (p: P) => <svg width={p.size ?? 18} height={p.size ?? 18} viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1" /><rect x="14" y="4" width="4" height="16" rx="1" /></svg>;
export const SkipBack = (p: P) => <S {...p}><path d="M19 20 9 12l10-8zM5 19V5" /></S>;
export const SkipFwd = (p: P) => <S {...p}><path d="m5 4 10 8-10 8zM19 5v14" /></S>;
export const Panel = (p: P) => <S {...p}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M15 4v16" /></S>;
export const Close = (p: P) => <S {...p}><path d="M6 6l12 12M18 6 6 18" /></S>;
export const Check = (p: P) => <S {...p}><path d="M5 12.5 10 17.5 19 7" /></S>;
export const Circle = (p: P) => <S {...p}><circle cx="12" cy="12" r="7" strokeDasharray="3 3" /></S>;
export const Alert = (p: P) => <S {...p}><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /></S>;
export const Lock = (p: P) => <S {...p}><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></S>;
export const Script = (p: P) => <S {...p}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></S>;
