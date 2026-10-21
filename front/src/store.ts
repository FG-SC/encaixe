// App state (Zustand): role + tab navigation (no router), who is logged in, and the public rules.
// The profile ids come from GET /api/me (the server session), never from localStorage: a shared browser must not
// reopen the previous person's profile.
import { create } from "zustand";
import type { Me, RulesPublic } from "./api";

export type Role = "candidate" | "recruiter";
export type CandidateTab = "onboarding" | "xray" | "deck" | "applications" | "explore" | "profile";
export type RecruiterTab = "jobs" | "deck" | "funnel" | "matches";
export type Overlay = "rules" | "dev" | null;

interface Persisted {
  role: Role;
  jobId: number | null;
}

interface State extends Persisted {
  me: Me | null; // null until GET /api/me answers
  candidateId: number | null;
  recruiterId: number | null;
  candidateTab: CandidateTab;
  recruiterTab: RecruiterTab;
  overlay: Overlay;
  rules: RulesPublic | null;
  match: { title: string; text: string } | null;
  setMe: (me: Me) => void;
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
    if (raw) {
      const saved = JSON.parse(raw);
      return { role: saved.role === "recruiter" ? "recruiter" : "candidate", jobId: saved.jobId ?? null };
    }
  } catch {
    /* storage unavailable: defaults */
  }
  return { role: "candidate", jobId: null };
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
    const { role, jobId } = get();
    save({ role, jobId });
  };
  const initial = load();
  return {
    ...initial,
    me: null,
    candidateId: null,
    recruiterId: null,
    candidateTab: "onboarding",
    recruiterTab: "jobs",
    overlay: null,
    rules: null,
    match: null,
    setMe: (me) => {
      const candidateId = me.account?.candidate_id ?? null;
      const recruiterId = me.account?.recruiter_id ?? null;
      const sameRecruiter = recruiterId === get().recruiterId;
      set({
        me,
        candidateId,
        recruiterId,
        candidateTab: candidateId ? (get().candidateId === candidateId ? get().candidateTab : "deck") : "onboarding",
        jobId: sameRecruiter ? get().jobId : null,
        overlay: null,
      });
      persist();
    },
    setRole: (role) => { set({ role, overlay: null }); persist(); },
    setCandidate: (candidateId, tab) => {
      set({ candidateId, candidateTab: tab ?? (candidateId ? "deck" : "onboarding"), overlay: null });
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
