import { render } from "@testing-library/react";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { StrictMode, useEffect } from "react";
import { describe, expect, it, vi } from "vitest";
import { type EventIn, impressionId, Outbox } from "../src/lib/outbox";
import { currentSession, resetSessionMemory, type StorageLike } from "../src/lib/session";
import { decide, swipeThreshold } from "../src/lib/swipe";

function memoryStorage(): StorageLike & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
}

describe("session", () => {
  it("keeps the session within the idle window and renews after it", () => {
    resetSessionMemory();
    const s = memoryStorage();
    let n = 0;
    const id = () => `id-${++n}`;
    const t0 = 1_000_000;
    const a = currentSession(30, t0, s, id);
    const b = currentSession(30, t0 + 29 * 60_000, s, id); // activity refreshes the window
    const c = currentSession(30, t0 + 29 * 60_000 + 29 * 60_000, s, id);
    const d = currentSession(30, t0 + 29 * 60_000 + 29 * 60_000 + 31 * 60_000, s, id);
    expect([a, b, c]).toEqual(["id-1", "id-1", "id-1"]);
    expect(d).toBe("id-2");
  });

  it("survives a reload (same storage) and works without storage", () => {
    resetSessionMemory();
    const s = memoryStorage();
    const a = currentSession(30, 0, s, () => "x");
    resetSessionMemory(); // "reload"
    expect(currentSession(30, 1000, s, () => "y")).toBe(a);
    resetSessionMemory();
    expect(currentSession(30, 0, null, () => "m")).toBe("m");
    expect(currentSession(30, 1, null, () => "other")).toBe("m");
  });
});

const ev = (over: Partial<EventIn> = {}): EventIn => ({
  client_event_id: "e1", actor_type: "candidate", actor_id: 1, item_type: "job", item_id: 2, type: "impression",
  session_id: "s", ...over,
});

describe("outbox", () => {
  it("posts each client_event_id once", async () => {
    const post = vi.fn(async (events: EventIn[]) => ({ results: events.map((e) => ({ ...e, event_id: 1, created: true,
      impression_auto_created: false, match: null })) }));
    const box = new Outbox(post);
    await Promise.all([box.send(ev()), box.send(ev()), box.send(ev({ client_event_id: "e2" }))]);
    expect(post).toHaveBeenCalledTimes(2);
  });

  it("impression ids are deterministic per actor, item, session and ranker", () => {
    const base = { actor_type: "candidate" as const, actor_id: 1, item_id: 2, session_id: "s", context_job_id: null };
    expect(impressionId(base, "feedback-v1")).toBe(impressionId(base, "feedback-v1"));
    expect(impressionId(base, "feedback-v1")).not.toBe(impressionId({ ...base, session_id: "t" }, "feedback-v1"));
    expect(impressionId(base, "feedback-v1")).not.toBe(impressionId(base, "static-v1"));
  });

  it("StrictMode double effects still post a single impression", async () => {
    const post = vi.fn(async (events: EventIn[]) => ({ results: events.map((e) => ({ ...e, event_id: 1, created: true,
      impression_auto_created: false, match: null })) }));
    const box = new Outbox(post);
    function Card() {
      useEffect(() => {
        const base = { actor_type: "candidate" as const, actor_id: 1, item_id: 9, session_id: "s" };
        void box.send(ev({ ...base, client_event_id: impressionId(base, "feedback-v1") }));
      }, []);
      return null;
    }
    render(<StrictMode><Card /></StrictMode>);
    await new Promise((r) => setTimeout(r, 0));
    expect(post).toHaveBeenCalledTimes(1);
  });
});

describe("swipe", () => {
  it("needs a minimum drag", () => {
    expect(swipeThreshold(200)).toBe(80);
    expect(swipeThreshold(800)).toBe(200);
    expect(decide(79, 200)).toBeNull();
    expect(decide(90, 200)).toBe("right");
    expect(decide(-250, 800)).toBe("left");
  });
});

describe("no hand-written rule numbers in the front", () => {
  it("timers and thresholds that are rules come from /api/rules/public", () => {
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const f of readdirSync(dir)) {
        const p = join(dir, f);
        if (statSync(p).isDirectory()) walk(p);
        else if (/\.(ts|tsx)$/.test(f)) files.push(p);
      }
    };
    walk(join(__dirname, "..", "src"));
    const offenders: string[] = [];
    for (const f of files) {
      const text = readFileSync(f, "utf8");
      // a timer with a literal delay (other than 0) would be a hidden rule (impression time, chips duration…)
      if (/setTimeout\([^,]+,\s*[1-9]\d*\s*\)/.test(text)) offenders.push(`${f}: literal timer`);
      for (const banned of ["impression_min_ms: 500", "session_idle_minutes: 30", "k_anon: 5", '"<5"']) {
        if (text.includes(banned)) offenders.push(`${f}: ${banned}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
