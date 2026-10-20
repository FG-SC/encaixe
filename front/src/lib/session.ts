// Session (spec 4): a UUID in localStorage, renewed after `idleMinutes` without activity.
// Reloading the page keeps the session. The idle time comes from /api/rules/public, never typed here.

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const KEY = "encaixe.session";

export function safeStorage(): StorageLike | null {
  try {
    const s = window.localStorage;
    s.getItem(KEY);
    return s;
  } catch {
    return null; // private mode, blocked storage: sessions live in memory only
  }
}

let memory: { id: string; last: number } | null = null;

export function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

/** Current session id; a new one when the last activity is older than `idleMinutes`. Touches activity. */
export function currentSession(
  idleMinutes: number,
  now: number = Date.now(),
  storage: StorageLike | null = safeStorage(),
  newId: () => string = uuid,
): string {
  let state: { id: string; last: number } | null = memory;
  if (storage) {
    try {
      const raw = storage.getItem(KEY);
      state = raw ? (JSON.parse(raw) as { id: string; last: number }) : null;
    } catch {
      state = null;
    }
  }
  if (!state || !state.id || now - state.last > idleMinutes * 60_000) {
    state = { id: newId(), last: now };
  } else {
    state = { id: state.id, last: now };
  }
  memory = state;
  if (storage) {
    try {
      storage.setItem(KEY, JSON.stringify(state));
    } catch {
      /* ignore */
    }
  }
  return state.id;
}

export function resetSessionMemory(): void {
  memory = null;
}
