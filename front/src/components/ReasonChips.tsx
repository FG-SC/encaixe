import { useEffect } from "react";
import type { Option } from "../api";

/** Reason chips after a swipe left. Optional reasons disappear after `seconds` (from /api/rules/public). */
export function ReasonChips({ options, seconds, required, onPick, title }: {
  options: Option[];
  seconds: number | null; // null = stays until a choice (required reasons)
  required: boolean;
  onPick: (reason: string | null) => void;
  title: string;
}) {
  useEffect(() => {
    if (required || seconds === null) return;
    const t = window.setTimeout(() => onPick(null), seconds * 1000);
    return () => window.clearTimeout(t);
  }, [required, seconds, onPick]);
  return (
    <div className="panel stack" role="dialog" aria-label={title}>
      <strong>{title}</strong>
      <div className="chips">
        {options.map((o) => (
          <button key={o.code} type="button" className="btn" onClick={() => onPick(o.code)}>{o.label}</button>
        ))}
        {!required && <button type="button" className="btn ghost" onClick={() => onPick(null)}>Sem motivo</button>}
      </div>
      {required && <span className="small muted">Recusar uma candidatura exige um motivo: ele vai para a pessoa.</span>}
    </div>
  );
}
