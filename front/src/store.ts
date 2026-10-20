// App state (Zustand): role + tab navigation (no router), who is using the app, and the public rules.
import { create } from "zustand";
import type { RulesPublic } from "./api";

export type Role = "candidate" | "recruiter";
export type CandidateTab = "onboarding" | "xray" | "deck" | "applications" | "explore" | "profile";
export type RecruiterTab = "jobs" | "deck" | "funnel" | "matches";
export type Overlay = "rules" | "dev" | null;

interface Persisted {
  role: Role;
  candidateId: number | null;
  recruiterId: number | null;
  jobId: number | null;
}

interface State extends Persisted {
  candidateTab: CandidateTab;
  recruiterTab: RecruiterTab;
  overlay: Overlay;
  rules: RulesPublic | null;
  match: { title: string; text: string } | null;
  setRole: (r: Role) => void;
  setCandidate: (id: number | null, tab?: CandidateTab) => void;
  setRecruiter: (id: number | null) => void;
  setJob: (id: number | null, tab?: RecruiterTab) => void;
  setCandidateTab: (t: CandidateTab) => void;
  setRecruiterTab: (t: RecruiterTab) => void;
  setOverlay: (o: Overlay) => void;
  setRules: (r: RulesPublic) => void;
  showMatch: (m: { title: string; text: string } | null) => void;
}

const KEY = "encaixe.app";

function load(): Persisted {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return { role: "candidate", candidateId: null, recruiterId: null, jobId: null, ...JSON.parse(raw) };
  } catch {
    /* storage unavailable: defaults */
  }
  return { role: "candidate", candidateId: null, recruiterId: null, jobId: null };
}

function save(s: Persisted): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* ignore */
  }
}

export const useApp = create<State>((set, get) => {
  const persist = () => {
    const { role, candidateId, recruiterId, jobId } = get();
    save({ role, candidateId, recruiterId, jobId });
  };
  const initial = load();
  return {
    ...initial,
    candidateTab: initial.candidateId ? "deck" : "onboarding",
    recruiterTab: "jobs",
    overlay: null,
    rules: null,
    match: null,
    setRole: (role) => { set({ role, overlay: null }); persist(); },
    setCandidate: (candidateId, tab) => {
      set({ candidateId, candidateTab: tab ?? (candidateId ? "deck" : "onboarding"), overlay: null });
      persist();
    },
    setRecruiter: (recruiterId) => { set({ recruiterId, jobId: null, recruiterTab: "jobs", overlay: null }); persist(); },
    setJob: (jobId, tab) => { set({ jobId, recruiterTab: tab ?? "deck" }); persist(); },
    setCandidateTab: (candidateTab) => set({ candidateTab, overlay: null }),
    setRecruiterTab: (recruiterTab) => set({ recruiterTab, overlay: null }),
    setOverlay: (overlay) => set({ overlay }),
    setRules: (rules) => set({ rules }),
    showMatch: (match) => set({ match }),
  };
});
