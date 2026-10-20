// Event outbox (spec 4): one POST per client_event_id, whatever happens (React StrictMode runs effects
// twice in development; retries after a network error reuse the same id; the server deduplicates too).

export interface RankMeta {
  rank_position?: number | null;
  rank_sum?: number | null;
  slot?: string | null;
  propensity?: number | null;
  ranker_version?: string | null;
  rank_detail?: unknown;
}

export interface EventIn extends RankMeta {
  client_event_id: string;
  actor_type: "candidate" | "recruiter";
  actor_id: number;
  item_type: "job" | "candidate";
  item_id: number;
  context_job_id?: number | null;
  type: "impression" | "swipe_right" | "swipe_left" | "open_detail";
  reason?: string | null;
  session_id: string;
}

export interface EventResult {
  event_id: number;
  client_event_id: string;
  created: boolean;
  type: string;
  impression_auto_created: boolean;
  match: { id: number; job_id: number; candidate_id: number; title: string } | null;
}

export type Poster = (events: EventIn[]) => Promise<{ results: EventResult[] }>;

export class Outbox {
  private inflight = new Map<string, Promise<EventResult>>();

  constructor(private post: Poster) {}

  send(event: EventIn): Promise<EventResult> {
    const known = this.inflight.get(event.client_event_id);
    if (known) return known;
    const p = this.post([event]).then((r) => r.results[0]);
    this.inflight.set(event.client_event_id, p);
    p.catch(() => this.inflight.delete(event.client_event_id)); // allow a retry with the same id
    return p;
  }

  sentIds(): string[] {
    return [...this.inflight.keys()];
  }
}

/** Deterministic id for an impression: the same card in the same session is one impression. */
export function impressionId(e: Pick<EventIn, "actor_type" | "actor_id" | "item_id" | "session_id" | "context_job_id">,
  rankerVersion: string | null | undefined): string {
  const key = `imp|${e.actor_type}|${e.actor_id}|${e.context_job_id ?? ""}|${e.item_id}|${e.session_id}|${rankerVersion ?? ""}`;
  return `imp-${hash(key)}`;
}

function hash(s: string): string {
  // FNV-1a 64-bit-ish (two 32-bit lanes), enough to make a stable, unique-looking id
  let h1 = 0x811c9dc5;
  let h2 = 0x01000193;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0;
    h2 = Math.imul(h2 ^ c, 0x811c9dc5) >>> 0;
  }
  return h1.toString(16).padStart(8, "0") + h2.toString(16).padStart(8, "0") + s.length.toString(16);
}
