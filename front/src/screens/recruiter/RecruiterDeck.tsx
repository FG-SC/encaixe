import { useState } from "react";
import { api, type CandidateCardData, type Deck } from "../../api";
import { Badges, Chips, ErrorBox, Loading, useAsync } from "../../components/common";
import { ExplainPanel } from "../../components/Explain";
import { ReasonChips } from "../../components/ReasonChips";
import { SwipeCard } from "../../components/SwipeCard";
import { outbox, swipeEvent, useImpression } from "../../lib/events";
import { currentSession } from "../../lib/session";
import type { Direction } from "../../lib/swipe";
import { useApp } from "../../store";

function BlindCard({ card, showWhy }: { card: CandidateCardData; showWhy: boolean }) {
  const p = card.candidate;
  return (
    <>
      <Badges items={card.badges} />
      <h2>{p.blind ? p.headline ?? "Perfil" : p.name}</h2>
      <div className="meta">{p.seniority_label}{p.city_id ? ` · ${p.city_id.split("-")[0]}` : ""}</div>
      <ul className="small">
        {p.experiences.slice(0, 4).map((e, i) => (
          <li key={i}><strong>{e.role}</strong>{e.company ? ` · ${e.company}` : ""} ({e.period})
            {e.internal_promotion ? " · promoção interna" : ""}
            {e.skills_used.length > 0 && <span className="muted"> — {e.skills_used.join(", ")}</span>}</li>
        ))}
      </ul>
      <Chips items={card.requirements.must} title="Requisitos obrigatórios desta vaga" />
      <p className="small">{card.good_fit.text}</p>
      {p.blind && <p className="small muted">Card cego até o encaixe: sem {p.hidden_fields.join(", ")}.</p>}
      {showWhy && <ExplainPanel e={card.explanation} />}
    </>
  );
}

export function RecruiterDeck() {
  const rules = useApp((s) => s.rules)!;
  const recruiterId = useApp((s) => s.recruiterId)!;
  const jobId = useApp((s) => s.jobId);
  const showMatch = useApp((s) => s.showMatch);
  const sessionId = currentSession(rules.events.session_idle_minutes);
  const deck = useAsync(() => jobId ? api.get<Deck<CandidateCardData>>(
    `/api/recruiters/${recruiterId}/jobs/${jobId}/deck?session_id=${sessionId}&limit=20`) : Promise.resolve(null),
  [recruiterId, jobId]);
  const [index, setIndex] = useState(0);
  const [why, setWhy] = useState(false);
  const [pendingLeft, setPendingLeft] = useState<CandidateCardData | null>(null);
  const [error, setError] = useState<unknown>(null);
  const cards = deck.data?.cards ?? [];
  const card = pendingLeft ? null : cards[index] ?? null;
  const actor = jobId ? { actor_type: "recruiter" as const, actor_id: recruiterId, context_job_id: jobId } : null;
  useImpression(actor, card, rules.events.session_idle_minutes, rules.events.impression_min_ms);

  if (!jobId) return <p className="muted">Escolha uma vaga em "Suas vagas".</p>;
  const next = () => {
    setWhy(false);
    if (index + 1 >= cards.length) { setIndex(0); deck.reload(); } else setIndex(index + 1);
  };
  const judge = async (c: CandidateCardData, liked: boolean, reason: string | null) => {
    try {
      const res = await outbox.send(swipeEvent(actor!, c, currentSession(rules.events.session_idle_minutes), liked, reason));
      if (res.match) showMatch({ title: res.match.title, text: "O contato da pessoa está liberado em Encaixes." });
    } catch (e) {
      setError(e);
    }
  };
  const onSwipe = (d: Direction) => {
    if (!card) return;
    if (d === "right") { judge(card, true, null); next(); } else { setPendingLeft(card); }
  };

  if (deck.loading && !deck.data) return <Loading text="Ordenando candidatos…" />;
  if (deck.error) return <ErrorBox error={deck.error} />;
  return (
    <section className="stack" aria-labelledby="rdeck-title">
      <h1 id="rdeck-title" style={{ margin: 0 }}>Candidatos</h1>
      {deck.data?.notice && <p className="notice small">{deck.data.notice}</p>}
      <p className="small muted">{deck.data?.n_eligible} perfis na lista · {(deck.data as unknown as { n_applicants: number })
        ?.n_applicants ?? 0} candidatura(s) · filtrados: {deck.data?.n_filtered}</p>
      <ErrorBox error={error} />
      {pendingLeft && (
        <ReasonChips title="Motivo da recusa (vai para a pessoa, com o que faltou)" options={rules.reasons.recruiter}
          seconds={null} required={pendingLeft.applicant && rules.reasons.recruiter_required_for_applicants}
          onPick={(r) => { judge(pendingLeft, false, r); setPendingLeft(null); next(); }} />
      )}
      <div className="deck">
        {card ? (
          <SwipeCard key={card.item_id} onSwipe={onSwipe} label={`Perfil: ${card.candidate.headline ?? ""}`}>
            <BlindCard card={card} showWhy={why} />
            <button type="button" className="btn ghost" data-no-swipe onClick={() => setWhy(!why)}>
              {why ? "Esconder explicação" : "Por que estou vendo isto?"}</button>
          </SwipeCard>
        ) : !pendingLeft && <div className="panel">Sem mais perfis por agora.</div>}
      </div>
    </section>
  );
}
