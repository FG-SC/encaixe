import { type FormEvent, useEffect, useState } from "react";
import { ApiError, api, type Me, onUnauthorized, type RulesPublic } from "./api";
import { ErrorBox, Loading, useAsync } from "./components/common";
import { Header } from "./components/Header";
import { MatchOverlay } from "./components/MatchOverlay";
import { Applications } from "./screens/candidate/Applications";
import { Deck } from "./screens/candidate/Deck";
import { Explore } from "./screens/candidate/Explore";
import { Onboarding } from "./screens/candidate/Onboarding";
import { Profile } from "./screens/candidate/Profile";
import { XRay } from "./screens/candidate/XRay";
import { DevPanel } from "./screens/DevPanel";
import { ConfirmLogin, Login, loginToken } from "./screens/Login";
import { Funnel } from "./screens/recruiter/Funnel";
import { Jobs } from "./screens/recruiter/Jobs";
import { Matches } from "./screens/recruiter/Matches";
import { RecruiterDeck } from "./screens/recruiter/RecruiterDeck";
import { Rules } from "./screens/Rules";
import { type CandidateTab, type RecruiterTab, useApp } from "./store";

const CANDIDATE_TABS: [CandidateTab, string][] = [
  ["xray", "Raio-X"], ["deck", "Vagas"], ["applications", "Candidaturas"], ["explore", "Explorar"], ["profile", "Perfil"],
];
const RECRUITER_TABS: [RecruiterTab, string][] = [
  ["jobs", "Vagas"], ["deck", "Candidatos"], ["funnel", "Funil e Explorar"], ["matches", "Encaixes"],
];

function CandidateArea() {
  const { candidateId, candidateTab, setCandidateTab } = useApp();
  if (!candidateId || candidateTab === "onboarding") return <Onboarding />;
  return (
    <>
      <nav className="tabs" aria-label="Seções do candidato">
        {CANDIDATE_TABS.map(([t, label]) => (
          <button key={t} type="button" aria-current={candidateTab === t ? "page" : undefined}
            onClick={() => setCandidateTab(t)}>{label}</button>
        ))}
      </nav>
      {candidateTab === "xray" && <XRay />}
      {candidateTab === "deck" && <Deck />}
      {candidateTab === "applications" && <Applications />}
      {candidateTab === "explore" && <Explore />}
      {candidateTab === "profile" && <Profile />}
    </>
  );
}

function RecruiterSignup() {
  const setMe = useApp((s) => s.setMe);
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.post("/api/recruiters", { name, company });
      setMe(await api.get<Me>("/api/me"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  };
  return (
    <form className="card stack" onSubmit={create} aria-labelledby="rec-title">
      <h2 id="rec-title">Seu perfil de recrutador</h2>
      <label className="stack">Seu nome<input type="text" value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label className="stack">Empresa<input type="text" value={company} onChange={(e) => setCompany(e.target.value)} /></label>
      <button type="submit" className="btn primary" disabled={!name || !company}>Criar perfil</button>
      {error && <p role="alert" className="error">{error}</p>}
    </form>
  );
}

function RecruiterArea() {
  const { recruiterId, recruiterTab, setRecruiterTab } = useApp();
  if (!recruiterId) return <RecruiterSignup />;
  return (
    <>
      <nav className="tabs" aria-label="Seções do recrutador">
        {RECRUITER_TABS.map(([t, label]) => (
          <button key={t} type="button" aria-current={recruiterTab === t ? "page" : undefined}
            onClick={() => setRecruiterTab(t)}>{label}</button>
        ))}
      </nav>
      {recruiterTab === "jobs" && <Jobs />}
      {recruiterTab === "deck" && <RecruiterDeck />}
      {recruiterTab === "funnel" && <Funnel />}
      {recruiterTab === "matches" && <Matches />}
    </>
  );
}

function Footer() {
  const { me, setOverlay } = useApp();
  return (
    <footer className="foot small muted">
      <button type="button" className="btn ghost small" onClick={() => setOverlay("rules")}>Como o Encaixe decide</button>
      {me && <a href={me.source_url} target="_blank" rel="noreferrer">Código-fonte (AGPL-3.0)</a>}
    </footer>
  );
}

export function App() {
  const { me, setMe, role, overlay, setOverlay, rules, setRules } = useApp();
  const pub = useAsync(() => api.get<RulesPublic>("/api/rules/public"), []);
  const [meError, setMeError] = useState<unknown>(null);
  useEffect(() => { if (pub.data) setRules(pub.data); }, [pub.data, setRules]);
  useEffect(() => {
    const refresh = () => { api.get<Me>("/api/me").then(setMe).catch(setMeError); };
    onUnauthorized(refresh);
    if (!useApp.getState().me) refresh();
    return () => onUnauthorized(null);
  }, [setMe]);
  const token = loginToken();
  const error = pub.error ?? meError;
  let body;
  if (error) body = <ErrorBox error={error} />;
  else if (!rules || !me) body = <Loading />;
  else if (token) body = <ConfirmLogin token={token} />;
  else if (!me.account) body = <Login />;
  else body = role === "candidate" ? <CandidateArea /> : <RecruiterArea />;
  return (
    <div className="app">
      <Header />
      <main>{body}</main>
      <Footer />
      {overlay && (
        <div className="overlay" role="dialog" aria-modal="true" onClick={(e) => { if (e.target === e.currentTarget) setOverlay(null); }}>
          <div className="sheet stack">
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button type="button" className="btn" onClick={() => setOverlay(null)} aria-label="Fechar">Fechar</button>
            </div>
            {overlay === "rules" ? <Rules /> : <DevPanel />}
          </div>
        </div>
      )}
      <MatchOverlay />
    </div>
  );
}
