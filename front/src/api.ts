// Thin typed client for the FastAPI backend (same origin in production; proxied by Vite in dev).
import type { EventIn, EventResult } from "./lib/outbox";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let unauthorizedHandler: (() => void) | null = null;

/** Called on any 401 outside the login routes: the session expired or was closed elsewhere. */
export function onUnauthorized(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

async function request<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
  const init: RequestInit = { method, headers: {}, credentials: "same-origin" };
  if (form) init.body = form;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const res = await fetch(path, init);
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/api/auth/")) unauthorizedHandler?.();
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  postForm: <T>(path: string, form: FormData) => request<T>("POST", path, undefined, form),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
  events: (events: EventIn[]) => request<{ results: EventResult[] }>("POST", "/api/events", events),
};

// ---------------------------------------------------------------- shared payload types

export interface MeAccount {
  email: string;
  candidate_id: number | null;
  recruiter_id: number | null;
  terms_version: string | null;
  recruiter: { id: number; name: string; company: string | null } | null;
}

/** GET /api/me: who is logged in (account null = logged out); dev = local demo tools available. */
export interface Me {
  account: MeAccount | null;
  dev: boolean;
  source_url: string;
}

export interface Option {
  code: string;
  label: string;
}

export interface RulesPublic {
  rules_hash: string;
  events: { impression_min_ms: number; session_idle_minutes: number; reason_chips_seconds: number };
  exploration: { every: number };
  reasons: { candidate: Option[]; recruiter: Option[]; recruiter_required_for_applicants: boolean };
  arrangements: Option[];
  regimes: Option[];
  periods: Option[];
  language_levels: Option[];
  seniority: { level: number; label: string }[];
  privacy: { k_anon: number; below_k_label: string; candidate_default_visible: boolean; blind_hidden: Option[];
    texts: Record<string, string> };
}

export interface Chip {
  skill: string;
  label: string;
  status: string; // proven_recent | proven | partial | listed | listed_partial | missing
}

export interface ExplainLine {
  criterion: string;
  label: string;
  pillar: string | null;
  raw_text: string;
  position: number;
  position_text: string;
  unknown: boolean;
  not_applicable: boolean;
}

export interface Explanation {
  lines: ExplainLine[];
  pillars: { pillar: string; label: string; sum: number; position: number; text: string }[];
  final_sum: number;
  order: number;
  n_items: number;
  final_text: string;
  tie_break_text: string;
  applicants_first_text: string | null;
  history: { item_id: number; title: string; liked: boolean; weight: number; text: string }[];
  flags: string[];
  note: string;
  good_fit_text: string;
  summary: string;
  slot_text: string | null;
}

export interface CardBase {
  item_type: "job" | "candidate";
  item_id: number;
  requirements: { must: Chip[]; nice: Chip[] };
  good_fit: { is_good_fit: boolean; text: string };
  badges: Option[];
  rank_meta: { rank_position: number; rank_sum: number; slot: string; propensity: number; ranker_version: string;
    aggregator: string; rules_hash: string; rank_detail: unknown };
  explanation: Explanation;
}

export interface JobSummary {
  id: number;
  title: string;
  company: string | null;
  city: string | null;
  state: string | null;
  location_text: string | null;
  arrangement: string | null;
  arrangement_label: string;
  comp: { text: string } | null;
  regime: string | null;
  seniority_label: string;
  origin: "market" | "platform";
  status: string;
  source: { key: string; label: string; url: string | null; text: string };
}

export interface JobCardData extends CardBase {
  job: JobSummary;
  counterfactual: { kind: string; skills: string[]; preferences: unknown[]; text: string | null } | null;
}

export interface BlindProfile {
  blind: boolean;
  name: string | null;
  contact: string | null;
  headline: string | null;
  seniority_label: string;
  city_id: string | null;
  experiences: { role: string; company: string | null; period: string; skills_used: string[];
    internal_promotion: boolean }[];
  education: { degree: string | null; field: string | null; institution: string | null; in_progress: boolean }[];
  skills_proven: string[];
  skills_listed: string[];
  languages: { language: string; level: string | null }[];
  hidden_fields: string[];
}

export interface CandidateCardData extends CardBase {
  candidate: BlindProfile;
  applicant: boolean;
  revision_id: number | null;
}

export interface Deck<C> {
  cards: C[];
  n_open?: number;
  n_eligible: number;
  n_filtered: number | string;
  n_remaining: number;
  filtered_summary?: string;
  ranker_version: string;
  aggregator: string;
  history_active: boolean;
  rules_hash: string;
  notice?: string;
}
