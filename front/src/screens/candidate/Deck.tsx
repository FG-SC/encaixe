import { useCallback, useState } from "react";
import { api, type Deck as DeckT, type JobCardData } from "../../api";
import { Badges, Chips, ErrorBox, Loading, useAsync } from "../../components/common";
import { ExplainPanel } from "../../components/Explain";
import { ReasonChips } from "../../components/ReasonChips";
import { SwipeCard } from "../../components/SwipeCard";
import { outbox, swipeEvent, useImpression } from "../../lib/events";
import { currentSession } from "../../lib/session";
import type { Direction } from "../../lib/swipe";
import { useApp } from "../../store";

interface FilteredGroups {
  total: number;
  summary: string;
  groups: { code: string; title: string; count: number; adjust_hint: string; adjust: string | null;
    items: { job: { id: number; title: string; company: string | null; source: { text: string } };
      reasons: { code: string; detail: string }[] }[] }[];
}

export function JobCardBody({ card, showWhy }: { card: JobCardData; showWhy: boolean }) {
  const j = card.job;
  return (
    <>
      <Badges items={card.badges} />
      <h2>{j.title}</h2>
      <div className="meta">{j.company ?? "Empresa não informada"} · {j.city ? `${j.city}${j.state ? `, ${j.state}` : ""} · ` : ""}
        {j.arrangement_label}{j.regime ? ` · ${j.regime}` : ""} · {j.seniority_label}</div>
      <div className="meta">{j.comp ? j.comp.text : "salário não informado"}</div>
      <div className="small muted">{j.source.url ? <a href={j.source.url} target="_blank" rel="noreferrer">{j.source.text}</a>
        : j.source.text}</div>
      <div className="stack" style={{ marginTop: 10 }}>
        <Chips items={card.requirements.must} title="Requisitos obrigatórios" />
        <Chips items={card.requirements.nice} title="Desejáveis" />
      </div>
      <p className="small">{card.good_fit.text}</p>
      {card.counterfactual?.text && <p className="counterfactual small">{card.counterfactual.text}</p>}
      {showWhy && <ExplainPanel e={card.explanation} />}
    </>
  );
}

export function Deck() {
  const rules = useApp((s) => s.rules)!;
  const candidateId = useApp((s) => s.candidateId)!;
  const showMatch = useApp((s) => s.showMatch);
  const setTab = useApp((s) => s.setCandidateTab);
  const sessionId = currentSession(rules.events.session_idle_minutes);
  const deck = useAsync(() => api.get<DeckT<JobCardData>>(
    `/api/candidates/${candidateId}/deck?session_id=${sessionId}&limit=20`), [candidateId]);
  const [index, setIndex] = useState(0);
  const [why, setWhy] = useState(false);
  const [pendingLeft, setPendingLeft] = useState<JobCardData | null>(null);
  const [saved, setSaved] = useState<JobCardData | null>(null);
  const [showFiltered, setShowFiltered] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const cards = deck.data?.cards ?? [];
  const card = cards[index] ?? null;
  const actor = { actor_type: "candidate" as const, actor_id: candidateId };
  useImpression(card ? actor : null, card, rules.events.session_idle_minutes, rules.events.impression_min_ms);

  const next = () => {
    setWhy(false);
    if (index + 1 >= cards.length) {
      setIndex(0);
      deck.reload();
    } else setIndex(index + 1);
  };

  const judge = useCallback(async (c: JobCardData, liked: boolean, reason: string | null = null) => {
    try {
      const res = await outbox.send(swipeEvent(actor, c, currentSession(rules.events.session_idle_minutes), liked, reason));
      if (res.match) showMatch({ title: res.match.title, text: "A empresa também quer conversar. Seu contato foi liberado." });
      if (liked && c.job.origin === "market") setSaved(c);
    } catch (e) {
      setError(e);
    }
  }, [candidateId]); // eslint-disable-line react-hooks/exhaustive-deps

  const onSwipe = (d: Direction) => {
    if (!card) return;
    if (d === "right") {
      judge(card, true);
      next();
    } else {
      setPendingLeft(card);
      next();
    }
  };

  if (deck.loading && !deck.data) return <Loading text="Ordenando vagas…" />;
  if (deck.error) return <ErrorBox error={deck.error} />;
  return (
    <section className="stack" aria-labelledby="deck-title">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 id="deck-title" style={{ margin: 0 }}>Suas vagas</h1>
        <button type="button" className="btn" onClick={() => setShowFiltered(!showFiltered)}>
          {deck.data?.n_filtered} vagas filtradas</button>
      </div>
      {deck.data?.filtered_summary && <p className="small muted">{deck.data.filtered_summary}</p>}
      {showFiltered && <FilteredList onAdjust={() => setTab("profile")} />}
      <ErrorBox error={error} />
      {pendingLeft && (
        <ReasonChips title={`Por que não "${pendingLeft.job.title}"? (opcional)`} options={rules.reasons.candidate}
          seconds={rules.events.reason_chips_seconds} required={false}
          onPick={(r) => { judge(pendingLeft, false, r); setPendingLeft(null); }} />
      )}
      {saved && (
        <div className="notice row" role="status">
          Vaga salva: <strong>{saved.job.title}</strong>.
          {saved.job.source.url && <a href={saved.job.source.url} target="_blank" rel="noreferrer">candidatar-se no site da empresa</a>}
          <button type="button" className="btn ghost" onClick={() => setSaved(null)}>ok</button>
        </div>
      )}
      <div className="deck">
        {card ? (
          <SwipeCard key={card.item_id} onSwipe={onSwipe} label={`Vaga: ${card.job.title}`}>
            <JobCardBody card={card} showWhy={why} />
            <button type="button" className="btn ghost" data-no-swipe onClick={() => setWhy(!why)}>
              {why ? "Esconder explicação" : "Por que estou vendo isto?"}</button>
          </SwipeCard>
        ) : (
          <div className="panel">Você viu todas as vagas por agora. Volte depois ou ajuste suas preferências.</div>
        )}
      </div>
      <p className="small muted">Ranking: {deck.data?.ranker_version} ({deck.data?.aggregator})
        {deck.data?.history_active ? " · aprendendo com seus swipes" : ""} · regras {deck.data?.rules_hash}</p>
    </section>
  );
}

function FilteredList({ onAdjust }: { onAdjust: () => void }) {
  const candidateId = useApp((s) => s.candidateId)!;
  const { data, error, loading } = useAsync(() => api.get<FilteredGroups>(`/api/candidates/${candidateId}/filtered`),
    [candidateId]);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  return (
    <div className="panel stack" aria-label="Vagas que não te mostramos">
      <h2>Vagas que não te mostramos</h2>
      <p>{data.summary}</p>
      {data.groups.map((g) => (
        <details key={g.code}>
          <summary><strong>{g.count}</strong> {g.title}</summary>
          <p className="small muted">{g.adjust_hint}{g.adjust && (
            <> <button type="button" className="btn ghost small" onClick={onAdjust}>Ajustar preferências</button></>)}</p>
          <ul className="small">
            {g.items.map((it) => (
              <li key={it.job.id}><strong>{it.job.title}</strong>{it.job.company ? ` · ${it.job.company}` : ""} —{" "}
                {it.reasons.map((r) => r.detail).join(" ")}</li>
            ))}
          </ul>
        </details>
      ))}
    </div>
  );
}
