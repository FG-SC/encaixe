import { useEffect } from "react";
import { api, type RulesPublic } from "./api";
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

function RecruiterArea() {
  const { recruiterId, recruiterTab, setRecruiterTab } = useApp();
  if (!recruiterId) return <p className="muted">Escolha ou crie um perfil de recrutador no topo da página.</p>;
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

export function App() {
  const { role, overlay, setOverlay, rules, setRules } = useApp();
  const pub = useAsync(() => api.get<RulesPublic>("/api/rules/public"), []);
  useEffect(() => { if (pub.data) setRules(pub.data); }, [pub.data, setRules]);
  return (
    <div className="app">
      <Header />
      <main>
        {pub.error ? <ErrorBox error={pub.error} /> : !rules ? <Loading /> : role === "candidate" ? <CandidateArea />
          : <RecruiterArea />}
      </main>
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
