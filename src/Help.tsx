import { Fragment, type ReactNode } from "react";
import guide from "../docs/GETTING_STARTED.md?raw";
import * as I from "./icons";

/** Inline markdown: **bold**, *italic*, `code`. */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g).filter(Boolean).map((t, i) =>
    t.startsWith("**") ? <b key={i}>{t.slice(2, -2)}</b>
      : t.startsWith("`") ? <code key={i}>{t.slice(1, -1)}</code>
        : t.startsWith("*") && t.length > 2 ? <em key={i}>{t.slice(1, -1)}</em> : <Fragment key={i}>{t}</Fragment>);
}

/** Small renderer for the guide's markdown (headings, paragraphs, lists, tables, rules). */
function render(md: string): ReactNode[] {
  const out: ReactNode[] = [];
  const lines = md.split(/\r?\n/);
  let i = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (!l.trim()) { i++; continue; }
    if (l.startsWith("---")) { out.push(<hr key={i} />); i++; continue; }
    const h = l.match(/^(#{1,3}) (.*)/);
    if (h) { const T = (["h1", "h2", "h3"] as const)[h[1].length - 1]; out.push(<T key={i}>{inline(h[2])}</T>); i++; continue; }
    if (l.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        if (!/^\|[\s|:-]+\|$/.test(lines[i])) rows.push(lines[i].slice(1, -1).split("|").map((c) => c.trim()));
        i++;
      }
      out.push(<table key={i}><thead><tr>{rows[0].map((c, k) => <th key={k}>{inline(c)}</th>)}</tr></thead>
        <tbody>{rows.slice(1).map((r, k) => <tr key={k}>{r.map((c, n) => <td key={n}>{inline(c)}</td>)}</tr>)}</tbody></table>);
      continue;
    }
    if (/^(\d+\.|-) /.test(l)) {
      const ordered = /^\d+\./.test(l);
      const items: string[] = [];
      while (i < lines.length && /^(\d+\.|-) /.test(lines[i])) { items.push(lines[i].replace(/^(\d+\.|-) /, "")); i++; }
      const L = ordered ? "ol" : "ul";
      out.push(<L key={i}>{items.map((t, k) => <li key={k}>{inline(t)}</li>)}</L>);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#|\||---|\d+\. |- )/.test(lines[i])) { para.push(lines[i]); i++; }
    out.push(<p key={i}>{inline(para.join(" "))}</p>);
  }
  return out;
}

export function HelpSheet({ onClose }: { onClose: () => void }) {
  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet glass help-sheet" role="dialog" aria-label="Getting started" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><I.Close /></button>
        </div>
        <article className="guide">{render(guide)}</article>
      </div>
    </div>
  );
}
