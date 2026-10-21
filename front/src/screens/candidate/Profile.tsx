import { useEffect, useState } from "react";
import { api, type Me } from "../../api";
import { ErrorBox, Loading, useAsync } from "../../components/common";
import { type Profile as ProfileT, ProfileEditor } from "../../components/ProfileEditor";
import { useApp } from "../../store";

interface CandidateOut {
  id: number;
  visible_to_recruiters: boolean;
  llm_consent: boolean;
  profile: ProfileT | null;
  revisions: { id: number; ts: string; kind: string }[];
}

export function Profile() {
  const rules = useApp((s) => s.rules)!;
  const candidateId = useApp((s) => s.candidateId)!;
  const setMe = useApp((s) => s.setMe);
  const cand = useAsync(() => api.get<CandidateOut>(`/api/candidates/${candidateId}`), [candidateId]);
  const [draft, setDraft] = useState<ProfileT | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { if (cand.data?.profile) setDraft(cand.data.profile); }, [cand.data]);

  if (cand.loading && !cand.data) return <Loading />;
  if (cand.error) return <ErrorBox error={cand.error} />;
  if (!cand.data || !draft) return null;

  const save = async () => {
    try {
      const r = await api.put<{ changed: boolean; kind: string | null }>(`/api/candidates/${candidateId}/profile`, draft);
      setMsg(!r.changed ? "Nada mudou." : r.kind === "relevant"
        ? "Revisão relevante salva: recusas antigas perdem peso e vagas em que você não avançou podem voltar."
        : "Revisão menor salva.");
      cand.reload();
    } catch (e) {
      setError(e);
    }
  };
  const toggleVisible = async (v: boolean) => {
    await api.patch(`/api/candidates/${candidateId}/settings`, { visible_to_recruiters: v });
    cand.reload();
  };
  const exportData = async () => {
    const data = await api.get<unknown>(`/api/candidates/${candidateId}/export`);
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `encaixe-meus-dados-${candidateId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };
  const purge = async () => {
    if (!window.confirm("Apagar definitivamente seu perfil, histórico e encaixes?")) return;
    await api.del(`/api/candidates/${candidateId}`);
    setMe(await api.get<Me>("/api/me"));
  };

  return (
    <section className="stack" aria-labelledby="profile-title">
      <h1 id="profile-title">Perfil</h1>
      <label className="toggle"><input type="checkbox" checked={cand.data.visible_to_recruiters}
        onChange={(e) => toggleVisible(e.target.checked)} />{rules.privacy.texts.visibility_toggle}</label>
      <ProfileEditor value={draft} onChange={setDraft} rules={rules} />
      {msg && <p className="notice" role="status">{msg}</p>}
      <ErrorBox error={error} />
      <div className="row">
        <button type="button" className="btn primary" onClick={save}>Salvar alterações</button>
        <button type="button" className="btn" onClick={exportData}>Exportar meus dados (JSON)</button>
        <button type="button" className="btn danger" onClick={purge}>Apagar meu perfil</button>
      </div>
      <h2>Revisões</h2>
      <ul className="small">{cand.data.revisions.map((r) => (
        <li key={r.id}>{new Date(r.ts).toLocaleString("pt-BR")} — {r.kind === "relevant" ? "relevante" : "menor"}</li>
      ))}</ul>
    </section>
  );
}
