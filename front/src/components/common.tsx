import { type DependencyList, useCallback, useEffect, useRef, useState } from "react";
import type { Chip, Option } from "../api";

const STATUS_TEXT: Record<string, string> = {
  proven_recent: "comprovada recentemente",
  proven: "comprovada",
  partial: "parcial (skill relacionada)",
  listed: "só listada",
  listed_partial: "listada (relacionada)",
  missing: "não aparece no perfil",
};

export function Chips({ items, title }: { items: Chip[]; title?: string }) {
  if (!items.length) return null;
  return (
    <div className="stack" style={{ gap: 4 }}>
      {title && <span className="small muted">{title}</span>}
      <div className="chips">
        {items.map((c) => (
          <span key={c.skill} className={`chip ${c.status}`} title={STATUS_TEXT[c.status] ?? c.status}>
            {c.status.startsWith("proven") ? "✓ " : c.status === "missing" ? "○ " : "~ "}
            {c.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function Badges({ items }: { items: Option[] }) {
  if (!items.length) return null;
  return (
    <div className="chips">
      {items.map((b) => (
        <span key={b.code} className={`badge ${b.code}`}>{b.label}</span>
      ))}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="error" role="alert">{error instanceof Error ? error.message : String(error)}</div>;
}

export function Loading({ text = "Carregando…" }: { text?: string }) {
  return <p className="muted" aria-live="polite">{text}</p>;
}

/** Load data on mount / when deps change; `reload` refetches. */
export function useAsync<T>(fn: () => Promise<T>, deps: DependencyList) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const run = useCallback(() => {
    const my = ++seq.current;
    setLoading(true);
    fn()
      .then((d) => { if (my === seq.current) { setData(d); setError(null); } })
      .catch((e) => { if (my === seq.current) setError(e); })
      .finally(() => { if (my === seq.current) setLoading(false); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { run(); }, [run]);
  return { data, error, loading, reload: run, setData };
}
