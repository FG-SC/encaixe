import { useState } from "react";
import { api } from "../api";
import { useApp } from "../store";
import { useAsync } from "./common";

interface CandRow { id: number; name: string; headline: string | null; synthetic: boolean }
interface RecRow { id: number; name: string; company: string | null; synthetic: boolean }

export function Header() {
  const { role, setRole, candidateId, setCandidate, recruiterId, setRecruiter, setOverlay } = useApp();
  const cands = useAsync(() => api.get<CandRow[]>("/api/candidates?limit=60"), [candidateId]);
  const recs = useAsync(() => api.get<RecRow[]>("/api/recruiters"), [recruiterId]);
  const [newRec, setNewRec] = useState(false);
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");

  const createRecruiter = async () => {
    const r = await api.post<{ id: number }>("/api/recruiters", { name, company });
    setNewRec(false);
    setRecruiter(r.id);
    recs.reload();
  };

  return (
    <header className="top">
      <a className="brand" href="#" onClick={(e) => { e.preventDefault(); setOverlay(null); }}>
        <span aria-hidden="true">🧩</span><strong>Encaixe</strong><small>vagas com regras abertas</small>
      </a>
      <div className="row">
        <div className="seg" role="group" aria-label="Papel">
          <button type="button" aria-pressed={role === "candidate"} onClick={() => setRole("candidate")}>Candidato</button>
          <button type="button" aria-pressed={role === "recruiter"} onClick={() => setRole("recruiter")}>Recrutador</button>
        </div>
        {role === "candidate" ? (
          <select aria-label="Perfil de candidato" value={candidateId ?? ""}
            onChange={(e) => setCandidate(e.target.value ? Number(e.target.value) : null)}>
            <option value="">+ Novo perfil</option>
            {(cands.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.name || `Perfil ${c.id}`}{c.synthetic ? " (sintético)" : ""}</option>
            ))}
          </select>
        ) : newRec ? (
          <span className="row">
            <input type="text" placeholder="Seu nome" aria-label="Nome" value={name} onChange={(e) => setName(e.target.value)} />
            <input type="text" placeholder="Empresa" aria-label="Empresa" value={company}
              onChange={(e) => setCompany(e.target.value)} />
            <button type="button" className="btn primary" disabled={!name || !company} onClick={createRecruiter}>Criar</button>
          </span>
        ) : (
          <select aria-label="Perfil de recrutador" value={recruiterId ?? ""} onChange={(e) => {
            if (e.target.value === "new") setNewRec(true);
            else setRecruiter(e.target.value ? Number(e.target.value) : null);
          }}>
            <option value="">Escolha…</option>
            {(recs.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.name} · {r.company}</option>)}
            <option value="new">+ Novo recrutador</option>
          </select>
        )}
        <button type="button" className="btn ghost" onClick={() => setOverlay("rules")}>Como o Encaixe decide</button>
        <button type="button" className="btn ghost small" onClick={() => setOverlay("dev")}>Painel de dev</button>
      </div>
    </header>
  );
}
