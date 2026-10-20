import { api, type JobSummary } from "../../api";
import { ErrorBox, Loading, useAsync } from "../../components/common";
import { useApp } from "../../store";

interface Application {
  job: JobSummary;
  status: string;
  status_label: string;
  applied_at: string;
  seen_at: string | null;
  decided_at: string | null;
  feedback?: { message_lines: string[]; reason_label: string; good_fit_rule: string };
}

interface Saved {
  job: JobSummary;
  apply_url: string | null;
  apply_text: string;
}

const STEPS = [
  ["sent", "enviada"],
  ["seen", "vista pela empresa"],
  ["decided", "não avançou / encaixe"],
] as const;

const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("pt-BR") : "");

export function Applications() {
  const candidateId = useApp((s) => s.candidateId)!;
  const apps = useAsync(() => api.get<Application[]>(`/api/candidates/${candidateId}/applications`), [candidateId]);
  const saved = useAsync(() => api.get<Saved[]>(`/api/candidates/${candidateId}/saved`), [candidateId]);
  if (apps.loading && !apps.data) return <Loading />;
  return (
    <section className="stack" aria-labelledby="apps-title">
      <h1 id="apps-title">Candidaturas</h1>
      <ErrorBox error={apps.error} />
      {(apps.data ?? []).length === 0 && <p className="muted">Nenhuma candidatura ainda: dê swipe à direita numa vaga
        publicada na plataforma.</p>}
      {(apps.data ?? []).map((a) => (
        <article key={a.job.id} className="panel stack">
          <h2 style={{ margin: 0 }}>{a.job.title} <span className="small muted">· {a.job.company}</span></h2>
          <ol className="timeline" aria-label="Status da candidatura">
            <li className="done">{STEPS[0][1]} {day(a.applied_at)}</li>
            <li className={a.seen_at ? "done" : ""}>{STEPS[1][1]} {day(a.seen_at)}</li>
            <li className={a.decided_at ? "done" : ""}>{a.status === "not_advanced" || a.status === "matched"
              ? a.status_label : STEPS[2][1]} {day(a.decided_at)}</li>
          </ol>
          {a.status === "matched" && <p className="notice">É um encaixe! A empresa recebeu seu contato.</p>}
          {a.feedback && (
            <div className="stack">
              {a.feedback.message_lines.map((l, i) => <p key={i} style={{ margin: 0 }}
                dangerouslySetInnerHTML={{ __html: escapeBold(l) }} />)}
              <p className="small muted">Bom encaixe: {a.feedback.good_fit_rule}.</p>
            </div>
          )}
        </article>
      ))}
      <h2>Vagas salvas</h2>
      {(saved.data ?? []).length === 0 && <p className="muted small">Vagas de mercado em que você deu swipe à direita
        aparecem aqui, com o link para se candidatar no site da empresa.</p>}
      <ul>
        {(saved.data ?? []).map((s) => (
          <li key={s.job.id}><strong>{s.job.title}</strong> · {s.job.company} — {s.apply_url
            ? <a href={s.apply_url} target="_blank" rel="noreferrer">{s.apply_text}</a> : s.job.source.text}</li>
        ))}
      </ul>
    </section>
  );
}

/** Server messages use **bold**; everything else is escaped. */
function escapeBold(s: string): string {
  const esc = s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}
