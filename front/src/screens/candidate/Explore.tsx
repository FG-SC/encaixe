import * as Plot from "@observablehq/plot";
import { useMemo } from "react";
import { api } from "../../api";
import { ErrorBox, Loading, useAsync } from "../../components/common";
import { GeoMap, type GeoPoint } from "../../components/GeoMap";
import { PlotChart } from "../../components/PlotChart";
import { useApp } from "../../store";
import { MarketMap } from "./XRay";

interface ExploreData {
  map: never;
  star: never;
  cities: { city_id: string; name: string; lat: number; lon: number; total: number; good_fit?: number; eligible?: number;
    filtered?: number }[];
  remote: Record<string, number>;
  unlock: { skill: string; label: string; jobs: number; examples: string[] }[];
  salaries: { jobs: { job_id: number; title: string; min: number; max: number; approx_fx: boolean }[];
    comp_min: number | null };
  revealed: { reasons: { reason: string; label: string; count: number }[]; text: string | null };
  timeline: { ts: string; kind: string; good_fit: number }[];
}

export function Explore() {
  const candidateId = useApp((s) => s.candidateId)!;
  const { data, error, loading } = useAsync(() => api.get<ExploreData>(`/api/candidates/${candidateId}/explore`),
    [candidateId]);
  const points = useMemo<GeoPoint[]>(() => (data?.cities ?? []).map((c) => ({
    lat: c.lat, lon: c.lon, value: c.total, color: (c.good_fit ?? 0) > 0 ? "#16A34A" : "#0E7C66",
    label: `${c.name}: ${c.total} vaga(s), ${c.good_fit ?? 0} bom encaixe, ${c.filtered ?? 0} filtradas`,
  })), [data]);
  const unlockPlot = useMemo<Plot.PlotOptions>(() => ({
    marginLeft: 140, height: 40 + 28 * (data?.unlock.length ?? 0), x: { label: "vagas que virariam bom encaixe", grid: true },
    y: { label: null },
    marks: [Plot.barX(data?.unlock ?? [], { y: "label", x: "jobs", fill: "#0E7C66", sort: { y: "-x" } }),
      Plot.ruleX([0])],
  }), [data]);
  const salaryPlot = useMemo<Plot.PlotOptions>(() => ({
    marginLeft: 180, height: 40 + 24 * (data?.salaries.jobs.length ?? 0), x: { label: "R$/mês", grid: true },
    y: { label: null },
    marks: [
      Plot.ruleY(data?.salaries.jobs ?? [], { y: "title", x1: "min", x2: "max", stroke: "#0E7C66", strokeWidth: 6 }),
      ...(data?.salaries.comp_min ? [Plot.ruleX([data.salaries.comp_min], { stroke: "#F59E0B", strokeWidth: 2 })] : []),
    ],
  }), [data]);
  const timelinePlot = useMemo<Plot.PlotOptions>(() => ({
    height: 180, x: { type: "time", label: null }, y: { label: "bons encaixes", grid: true },
    marks: [Plot.line(data?.timeline ?? [], { x: (d: { ts: string }) => new Date(d.ts), y: "good_fit", stroke: "#0E7C66" }),
      Plot.dot(data?.timeline ?? [], { x: (d: { ts: string }) => new Date(d.ts), y: "good_fit",
        fill: (d: { kind: string }) => (d.kind === "relevant" ? "#F59E0B" : "#9CA3AF"), r: 5 })],
  }), [data]);

  if (loading && !data) return <Loading text="Calculando o mercado…" />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  return (
    <section className="stack" aria-labelledby="explore-title">
      <h1 id="explore-title">Explorar</h1>
      <div className="grid2">
        <div className="panel"><h2>Mapa do mercado</h2>
          <MarketMap data={data as unknown as Parameters<typeof MarketMap>[0]["data"]} />
          <p className="small muted">Cada ponto é uma vaga aberta; cores são áreas; pontos maiores são bom encaixe.</p></div>
        <div className="panel"><h2>Onde estão as vagas</h2>
          <GeoMap points={points} label="Vagas por cidade" />
          <p className="small muted">Remotas: {data.remote.good_fit ?? 0} bom encaixe, {data.remote.eligible ?? 0} na lista,
            {" "}{data.remote.filtered ?? 0} filtradas.</p></div>
      </div>
      <div className="panel"><h2>Qual skill destrava mais vagas</h2>
        <PlotChart options={unlockPlot} label="Skills que mais destravam vagas" />
        <ul className="small">{data.unlock.slice(0, 5).map((u) => (
          <li key={u.skill}><strong>{u.label}</strong>: {u.examples.join("; ") || "—"}</li>))}</ul>
        <p className="small muted">Cada barra simula a skill usada numa experiência recente e reconta os bons encaixes.</p>
      </div>
      <div className="grid2">
        <div className="panel"><h2>Salários dos seus bons encaixes</h2>
          {data.salaries.jobs.length ? <PlotChart options={salaryPlot} label="Faixas salariais dos bons encaixes" />
            : <p className="muted">Nenhum bom encaixe informa salário.</p>}
          <p className="small muted">A linha laranja é o seu mínimo. Moedas estrangeiras usam câmbio aproximado.</p></div>
        <div className="panel"><h2>O que seus swipes revelam</h2>
          <ul>{data.revealed.reasons.map((r) => <li key={r.reason}>{r.label}: {r.count}</li>)}</ul>
          {data.revealed.text && <p className="small">{data.revealed.text}</p>}
          {!data.revealed.reasons.length && <p className="muted small">Ainda não há recusas com motivo.</p>}</div>
      </div>
      <div className="panel"><h2>Seu perfil no tempo</h2>
        <PlotChart options={timelinePlot} label="Bons encaixes a cada revisão do perfil" />
        <p className="small muted">Pontos laranja são revisões relevantes; cada revisão é medida contra as vagas abertas hoje.</p>
      </div>
    </section>
  );
}
