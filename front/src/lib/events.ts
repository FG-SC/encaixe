// Events from the UI: impressions after ≥ impression_min_ms on screen (once per card/session/ranker),
// swipes with the card's rank metadata. One outbox for the whole app.
import { useEffect } from "react";
import { api, type CardBase } from "../api";
import { type EventIn, impressionId, Outbox } from "./outbox";
import { currentSession, uuid } from "./session";

export const outbox = new Outbox(api.events);

export interface Actor {
  actor_type: "candidate" | "recruiter";
  actor_id: number;
  context_job_id?: number | null;
}

function meta(card: CardBase) {
  const m = card.rank_meta;
  return {
    rank_position: m.rank_position, rank_sum: m.rank_sum, slot: m.slot, propensity: m.propensity,
    ranker_version: m.ranker_version, rank_detail: m.rank_detail,
  };
}

export function impressionEvent(actor: Actor, card: CardBase, sessionId: string): EventIn {
  const base = {
    ...actor, item_type: card.item_type, item_id: card.item_id, session_id: sessionId,
  } as const;
  return { ...base, ...meta(card), type: "impression", client_event_id: impressionId(base, card.rank_meta.ranker_version) };
}

export function swipeEvent(actor: Actor, card: CardBase, sessionId: string, liked: boolean,
  reason: string | null = null): EventIn {
  return {
    ...actor, item_type: card.item_type, item_id: card.item_id, session_id: sessionId, ...meta(card),
    type: liked ? "swipe_right" : "swipe_left", reason, client_event_id: uuid(),
  };
}

/** Record an impression once the card has been visible for `minMs` (StrictMode-safe: deterministic id). */
export function useImpression(actor: Actor | null, card: CardBase | null, idleMinutes: number, minMs: number) {
  useEffect(() => {
    if (!actor || !card) return;
    const t = window.setTimeout(() => {
      outbox.send(impressionEvent(actor, card, currentSession(idleMinutes))).catch(() => undefined);
    }, minMs);
    return () => window.clearTimeout(t);
  }, [actor?.actor_type, actor?.actor_id, actor?.context_job_id, card?.item_id, card?.rank_meta.ranker_version,
    idleMinutes, minMs]); // eslint-disable-line react-hooks/exhaustive-deps
}
