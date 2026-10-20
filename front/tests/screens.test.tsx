// Every screen renders without crashing on real API responses (recorded from the demo server: synthetic data).
import { cleanup, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("leaflet", () => {
  const layer = { addTo: () => layer, on: () => layer, bindTooltip: () => layer };
  const map = { remove: () => undefined, removeLayer: () => undefined };
  return { default: { map: () => map, tileLayer: () => layer, circleMarker: () => layer } };
});
vi.mock("leaflet/dist/leaflet.css", () => ({}));

const fx = (name: string) => JSON.parse(readFileSync(join(__dirname, "fixtures", `${name}.json`), "utf8"));
const ids = fx("ids") as { rec: number; job: number };

const ROUTES: [RegExp, string][] = [
  [/\/api\/rules\/public$/, "rules_public"],
  [/\/api\/rules$/, "rules"],
  [/\/api\/candidates\?limit/, "candidates"],
  [/\/api\/recruiters$/, "recruiters"],
  [/\/api\/candidates\/\d+\/xray/, "xray"],
  [/\/api\/candidates\/\d+\/deck/, "deck"],
  [/\/api\/candidates\/\d+\/filtered/, "filtered"],
  [/\/api\/candidates\/\d+\/applications/, "applications"],
  [/\/api\/candidates\/\d+\/saved/, "saved"],
  [/\/api\/candidates\/\d+\/explore/, "explore"],
  [/\/api\/candidates\/\d+$/, "candidate"],
  [/\/api\/meta\/skills/, "skills"],
  [/\/api\/meta\/cities/, "cities"],
  [/\/api\/recruiters\/\d+\/jobs\/\d+\/deck/, "rdeck"],
  [/\/api\/recruiters\/\d+\/jobs\/\d+\/funnel/, "funnel"],
  [/\/api\/recruiters\/\d+\/jobs\/\d+\/explore/, "rexplore"],
  [/\/api\/recruiters\/\d+\/jobs$/, "rjobs"],
  [/\/api\/recruiters\/\d+\/matches/, "matches"],
  [/\/api\/dev\/status/, "dev"],
];

beforeAll(() => {
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    const url = String(input);
    const hit = ROUTES.find(([re]) => re.test(url));
    if (!hit) return new Response(JSON.stringify({ detail: `no fixture for ${url}` }), { status: 404 });
    return new Response(JSON.stringify(fx(hit[1])), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
});
afterEach(() => cleanup());

async function show(state: Record<string, unknown>) {
  const { useApp } = await import("../src/store");
  const { App } = await import("../src/App");
  useApp.setState({ rules: null, overlay: null, match: null, ...state });
  render(<App />);
}

describe("candidate screens", () => {
  it.each([
    ["xray", "Seu Raio-X"],
    ["deck", "Suas vagas"],
    ["applications", "Vagas salvas"],
    ["explore", "Qual skill destrava mais vagas"],
    ["profile", "Revisões"],
  ])("%s renders", async (tab, text) => {
    await show({ role: "candidate", candidateId: 5, candidateTab: tab });
    expect(await screen.findByText(text, {}, { timeout: 3000 })).toBeTruthy();
  });

  it("onboarding renders with the LLM consent unchecked", async () => {
    await show({ role: "candidate", candidateId: null, candidateTab: "onboarding" });
    const consent = await screen.findByLabelText(/Usar IA para ler meu CV/, {}, { timeout: 3000 });
    expect((consent as HTMLInputElement).checked).toBe(false);
  });

  it("deck shows the explanation only on demand", async () => {
    await show({ role: "candidate", candidateId: 5, candidateTab: "deck" });
    await screen.findByText("Por que estou vendo isto?", {}, { timeout: 3000 });
    expect(screen.queryByText(/A posição compara esta vaga/)).toBeNull();
    screen.getByText("Por que estou vendo isto?").click();
    expect(await screen.findByText(/A posição compara esta vaga/)).toBeTruthy();
  });
});

describe("recruiter screens", () => {
  it.each([
    ["jobs", "Publicar uma vaga"],
    ["deck", "Candidatos"],
    ["funnel", "Funil"],
    ["matches", "Encaixes"],
  ])("%s renders", async (tab, text) => {
    await show({ role: "recruiter", recruiterId: ids.rec, jobId: ids.job, recruiterTab: tab });
    expect((await screen.findAllByText(text, {}, { timeout: 3000 })).length).toBeGreaterThan(0);
  });
});

describe("overlays", () => {
  it.each([["rules", "Como o Encaixe decide"], ["dev", "Painel de dev"]])("%s renders", async (overlay, text) => {
    await show({ role: "candidate", candidateId: 5, candidateTab: "deck", overlay });
    expect((await screen.findAllByText(text, {}, { timeout: 3000 })).length).toBeGreaterThan(0);
  });
});
