import { api, type BlindProfile, type JobSummary } from "../../api";
import { ErrorBox, Loading, useAsync } from "../../components/common";
import { useApp } from "../../store";

interface MatchRow {
  match_id: number;
  ts: string;
  job: JobSummary | null;
  candidate: BlindProfile | null;
  contact_released_text: string;
}

export function Matches() {
  const recruiterId = useApp((s) => s.recruiterId)!;
  const { data, error, loading } = useAsync(() => api.get<MatchRow[]>(`/api/recruiters/${recruiterId}/matches`),
    [recruiterId]);
  if (loading && !data) return <Loading />;
  return (
    <section className="stack" aria-labelledby="matches-title">
      <h1 id="matches-title">Encaixes</h1>
      <ErrorBox error={error} />
      {(data ?? []).length === 0 && <p className="muted">Nenhum encaixe ainda.</p>}
      {(data ?? []).map((m) => (
        <article key={m.match_id} className="panel">
          <strong>{m.candidate?.name}</strong> — {m.job?.title}
          <div className="small">{m.candidate?.contact}</div>
          <div className="small muted">{m.contact_released_text} ({new Date(m.ts).toLocaleDateString("pt-BR")})</div>
        </article>
      ))}
    </section>
  );
}
