import { useState } from "react";
import { api } from "../api";
import { ErrorBox, Loading, useAsync } from "../components/common";

interface Status {
  clock: { now: string; offset_days: number };
  ranker: string;
  aggregator: string;
  embeddings: { requested: string | null; active: string | null; fallback_reason: string | null };
  llm: { state: string; reason: string | null; model: string; requests_today: number; tokens_today: number;
    cache_hits: number; queue_size: number };
  counts: Record<string, number>;
}

export function DevPanel() {
  const status = useAsync(() => api.get<Status>("/api/dev/status"), []);
  const [days, setDays] = useState(30);
  const [error, setError] = useState<unknown>(null);
  const act = async (fn: () => Promise<unknown>) => {
    try { await fn(); status.reload(); } catch (e) { setError(e); }
  };
  if (status.loading && !status.data) return <Loading />;
  const s = status.data;
  if (!s) return <ErrorBox error={status.error} />;
  return (
    <section className="stack" aria-labelledby="dev-title">
      <h1 id="dev-title">Painel de dev</h1>
      <ErrorBox error={error} />
      <div className="grid2">
        <div className="panel stack">
          <h2>Relógio da demo</h2>
          <p>{new Date(s.clock.now).toLocaleString("pt-BR")} (adiantado {s.clock.offset_days} dias)</p>
          <div className="row">
            <input type="number" min={1} value={days} onChange={(e) => setDays(Number(e.target.value))}
              aria-label="Dias para avançar" style={{ width: 90 }} />
            <button type="button" className="btn" onClick={() => act(() => api.post("/api/dev/clock", { advance_days: days }))}>
              Avançar o tempo</button>
            <button type="button" className="btn ghost" onClick={() => act(() => api.post("/api/dev/clock", { offset_days: 0 }))}>
              Voltar ao presente</button>
          </div>
        </div>
        <div className="panel stack">
          <h2>Ranking servido</h2>
          <div className="seg" role="group" aria-label="Ranker">
            {["static-v1", "feedback-v1"].map((r) => (
              <button key={r} type="button" aria-pressed={s.ranker === r}
                onClick={() => act(() => api.post("/api/dev/ranker", { ranker: r }))}>{r}</button>
            ))}
          </div>
          <div className="seg" role="group" aria-label="Agregador">
            {["rank_sum", "rrf", "weighted"].map((a) => (
              <button key={a} type="button" aria-pressed={s.aggregator === a}
                onClick={() => act(() => api.post("/api/dev/ranker", { aggregator: a }))}>{a}</button>
            ))}
          </div>
        </div>
        <div className="panel stack">
          <h2>IA</h2>
          <p><strong>{s.llm.state}</strong>{s.llm.reason ? ` — ${s.llm.reason}` : ""}</p>
          <p className="small">Modelo {s.llm.model} · {s.llm.requests_today} requisições hoje · {s.llm.tokens_today} tokens
            · {s.llm.cache_hits} acertos de cache · fila {s.llm.queue_size}</p>
        </div>
        <div className="panel stack">
          <h2>Embeddings e dados</h2>
          <p className="small">Backend: {s.embeddings.active ?? s.embeddings.requested}
            {s.embeddings.fallback_reason ? ` (fallback: ${s.embeddings.fallback_reason})` : ""}</p>
          <ul className="small">{Object.entries(s.counts).map(([k, v]) => <li key={k}>{k}: {v}</li>)}</ul>
        </div>
      </div>
    </section>
  );
}
