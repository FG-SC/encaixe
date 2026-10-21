import { api, type Me } from "../api";
import { useApp } from "../store";
import { useAsync } from "./common";

interface CandRow { id: number; name: string; headline: string | null; synthetic: boolean }
interface RecRow { id: number; name: string; company: string | null; synthetic: boolean }

/** Local demo only (me.dev): switch persona through the dev login; production has none of this. */
function DevPersonas() {
  const { role, candidateId, recruiterId, setMe } = useApp();
  const cands = useAsync(() => api.get<CandRow[]>("/api/candidates?limit=60"), [candidateId]);
  const recs = useAsync(() => api.get<RecRow[]>("/api/recruiters"), [recruiterId]);
  const loginAs = async (body: Record<string, unknown>) => setMe(await api.post<Me>("/api/dev/login", body));
  const fresh = () => loginAs({ email: `pessoa-${Date.now()}@demo.invalid` });

  return role === "candidate" ? (
    <select aria-label="Perfil de candidato (demo)" value={candidateId ?? ""}
      onChange={(e) => (e.target.value ? loginAs({ candidate_id: Number(e.target.value) }) : fresh())}>
      <option value="">+ Novo perfil</option>
      {(cands.data ?? []).map((c) => (
        <option key={c.id} value={c.id}>{c.name || `Perfil ${c.id}`}{c.synthetic ? " (sintético)" : ""}</option>
      ))}
    </select>
  ) : (
    <select aria-label="Perfil de recrutador (demo)" value={recruiterId ?? ""}
      onChange={(e) => (e.target.value === "new" ? fresh() : loginAs({ recruiter_id: Number(e.target.value) }))}>
      <option value="" disabled>Escolha…</option>
      {(recs.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.name} · {r.company}</option>)}
      <option value="new">+ Novo recrutador</option>
    </select>
  );
}

export function Header() {
  const { me, setMe, role, setRole, setOverlay } = useApp();
  const logout = async () => {
    await api.post("/api/auth/logout");
    if (me) setMe({ ...me, account: null });
  };

  return (
    <header className="top">
      <a className="brand" href="/" onClick={(e) => { e.preventDefault(); setOverlay(null); }}>
        <span aria-hidden="true">🧩</span><strong>Encaixe</strong><small>vagas com regras abertas</small>
      </a>
      <div className="row">
        {me?.account && (
          <div className="seg" role="group" aria-label="Papel">
            <button type="button" aria-pressed={role === "candidate"} onClick={() => setRole("candidate")}>Candidato</button>
            <button type="button" aria-pressed={role === "recruiter"} onClick={() => setRole("recruiter")}>Recrutador</button>
          </div>
        )}
        {me?.dev && <DevPersonas />}
        <button type="button" className="btn ghost" onClick={() => setOverlay("rules")}>Como o Encaixe decide</button>
        {me?.dev && (
          <button type="button" className="btn ghost small" onClick={() => setOverlay("dev")}>Painel de dev</button>
        )}
        {me?.account && (
          <span className="row small">
            <span className="muted">{me.account.email}</span>
            <button type="button" className="btn ghost small" onClick={logout}>Sair</button>
          </span>
        )}
      </div>
    </header>
  );
}
