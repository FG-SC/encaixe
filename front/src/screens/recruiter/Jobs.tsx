import { useState } from "react";
import { api, type JobSummary } from "../../api";
import { ErrorBox, Loading, useAsync } from "../../components/common";
import { useApp } from "../../store";

interface JobRow {
  job: JobSummary;
  n_applicants: number;
  n_matches: number;
}

interface JobDraft {
  title: string;
  company: string | null;
  location_text: string | null;
  requires: { skills_must: string[]; skills_nice: string[]; seniority: number | null; languages: { language: string }[] };
  offers: { arrangement: string | null; comp_min: number | null; comp_max: number | null; regime: string | null };
  warnings: string[];
  method: string;
  notice: string;
  [k: string]: unknown;
}

export function Jobs() {
  const recruiterId = useApp((s) => s.recruiterId)!;
  const setJob = useApp((s) => s.setJob);
  const rules = useApp((s) => s.rules)!;
  const jobs = useAsync(() => api.get<JobRow[]>(`/api/recruiters/${recruiterId}/jobs`), [recruiterId]);
  const [text, setText] = useState("");
  const [draft, setDraft] = useState<JobDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const label = (n: number | null) => rules.seniority.find((s) => s.level === n)?.label ?? "não informada";

  const parse = async () => {
    setBusy(true);
    setError(null);
    try {
      setDraft(await api.post<JobDraft>("/api/jobs/parse", { text }));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const publish = async () => {
    if (!draft) return;
    setBusy(true);
    try {
      const r = await api.post<{ job_id: number }>(`/api/recruiters/${recruiterId}/jobs`, { draft });
      setDraft(null);
      setText("");
      jobs.reload();
      setJob(r.job_id, "deck");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const setStatus = async (id: number, status: string) => {
    await api.patch(`/api/jobs/${id}`, { recruiter_id: recruiterId, status });
    jobs.reload();
  };

  return (
    <section className="stack" aria-labelledby="jobs-title">
      <h1 id="jobs-title">Suas vagas</h1>
      {jobs.loading && !jobs.data && <Loading />}
      <ErrorBox error={jobs.error} />
      {(jobs.data ?? []).map((r) => (
        <article key={r.job.id} className="panel row" style={{ justifyContent: "space-between" }}>
          <div>
            <strong>{r.job.title}</strong> <span className="small muted">· {r.job.arrangement_label} · {r.job.status}</span>
            <div className="small">{r.n_applicants} candidatura(s) · {r.n_matches} encaixe(s)</div>
          </div>
          <div className="row">
            <button type="button" className="btn primary" onClick={() => setJob(r.job.id, "deck")}>Ver candidatos</button>
            <button type="button" className="btn" onClick={() => setJob(r.job.id, "funnel")}>Funil e mercado</button>
            {r.job.status === "open"
              ? <button type="button" className="btn ghost" onClick={() => setStatus(r.job.id, "paused")}>Pausar</button>
              : <button type="button" className="btn ghost" onClick={() => setStatus(r.job.id, "open")}>Reabrir</button>}
          </div>
        </article>
      ))}
      <h2>Publicar uma vaga</h2>
      {!draft ? (
        <div className="stack">
          <textarea aria-label="Texto da vaga" value={text} onChange={(e) => setText(e.target.value)}
            placeholder="Cole o texto da vaga (a primeira linha é o título)…" />
          <ErrorBox error={error} />
          <div><button type="button" className="btn primary" disabled={busy || !text.trim()} onClick={parse}>
            {busy ? "Lendo…" : "Ler a vaga"}</button></div>
        </div>
      ) : (
        <div className="panel stack">
          <h3>{draft.title}</h3>
          {draft.warnings.map((w) => <p key={w} className="notice small">{w}</p>)}
          <p className="small">Obrigatórios: {draft.requires.skills_must.join(", ") || "—"}</p>
          <p className="small">Desejáveis: {draft.requires.skills_nice.join(", ") || "—"}</p>
          <p className="small">Senioridade: {label(draft.requires.seniority)} · Modalidade: {draft.offers.arrangement ?? "—"}
            {draft.offers.comp_max ? ` · até ${draft.offers.comp_max}` : " · salário não informado"}</p>
          <p className="notice">{draft.notice}</p>
          <ErrorBox error={error} />
          <div className="row">
            <button type="button" className="btn" onClick={() => setDraft(null)}>Voltar</button>
            <button type="button" className="btn primary" disabled={busy} onClick={publish}>Publicar</button>
          </div>
        </div>
      )}
    </section>
  );
}
