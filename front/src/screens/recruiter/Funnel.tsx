import * as Plot from "@observablehq/plot";
import { useMemo } from "react";
import { api } from "../../api";
import { ErrorBox, Loading, useAsync } from "../../components/common";
import { GeoMap } from "../../components/GeoMap";
import { PlotChart } from "../../components/PlotChart";
import { useApp } from "../../store";

interface FunnelData {
  stages: { code: string; label: string; count: string }[];
  requirements: { skill: string; label: string; proving: string; good_fit_without_it: string }[];
  bottleneck: { label: string; text: string } | null;
  filters: { code: string; title: string; count: string }[];
  note: string;
}

interface ExploreData {
  job: { title: string; x: number | null; y: number | null };
  pool_size: string;
  pool_map: { grid: number; cells: { x: number; y: number; count: number }[]; hidden_cells: number };
  cities: { name: string; lat: number; lon: number; count: number }[];
  benchmark: { jobs: { title: string; similarity: number; comp_brl_month: number | null; approx_fx: boolean }[];
    n_with_salary: number; p25: number | null; p50: number | null; p75: number | null; own_comp_brl_month: number | null };
  candidate_reasons: { total: string; rows: { label: string; count: string }[]; note: string };
  congestion: { top5_in_other_lists: string; text: string };
}

const money = (x: number | null) => (x == null ? "—" : `R$ ${Math.round(x).toLocaleString("pt-BR")}`);

export function Funnel() {
  const recruiterId = useApp((s) => s.recruiterId)!;
  const jobId = useApp((s) => s.jobId);
  const funnel = useAsync(() => jobId ? api.get<FunnelData>(`/api/recruiters/${recruiterId}/jobs/${jobId}/funnel`)
    : Promise.resolve(null), [recruiterId, jobId]);
  const ex = useAsync(() => jobId ? api.get<ExploreData>(`/api/recruiters/${recruiterId}/jobs/${jobId}/explore`)
    : Promise.resolve(null), [recruiterId, jobId]);
  const poolPlot = useMemo<Plot.PlotOptions>(() => ({
    height: 260, inset: 10, x: { axis: null, domain: [0, 1] }, y: { axis: null, domain: [0, 1] },
    marks: [
      Plot.dot(ex.data?.pool_map.cells ?? [], { x: "x", y: "y", r: "count", fill: "#0E7C66", fillOpacity: 0.6,
        title: (d: { count: number }) => `${d.count} perfis` }),
      ...(ex.data?.job.x != null ? [Plot.text([ex.data.job], { x: "x", y: "y", text: () => "◆", fontSize: 20,
        fill: "#F59E0B" })] : []),
    ],
  }), [ex.data]);
  if (!jobId) return <p className="muted">Escolha uma vaga em "Suas vagas".</p>;
  if ((funnel.loading && !funnel.data) || (ex.loading && !ex.data)) return <Loading />;
  const f = funnel.data;
  const e = ex.data;
  return (
    <section className="stack" aria-labelledby="funnel-title">
      <h1 id="funnel-title">Funil e mercado{e ? `: ${e.job.title}` : ""}</h1>
      <ErrorBox error={funnel.error || ex.error} />
      {f && (
        <div className="grid2">
          <div className="panel"><h2>Funil</h2>
            <ol>{f.stages.map((s) => <li key={s.code}>{s.label}: <strong>{s.count}</strong></li>)}</ol>
            <p className="small muted">{f.note}</p></div>
          <div className="panel"><h2>Qual requisito está esvaziando o funil</h2>
            {f.bottleneck ? <p className="notice">{f.bottleneck.text}</p> : <p className="muted">Nenhum requisito sozinho
              aumentaria os bons encaixes.</p>}
            <table className="small" style={{ width: "100%" }}>
              <thead><tr><th>Requisito</th><th>comprovam</th><th>bons encaixes sem ele</th></tr></thead>
              <tbody>{f.requirements.map((r) => (
                <tr key={r.skill}><td>{r.label}</td><td>{r.proving}</td><td>{r.good_fit_without_it}</td></tr>))}</tbody>
            </table>
            {f.filters.length > 0 && <p className="small">Filtrados: {f.filters.map((x) => `${x.title} (${x.count})`).join("; ")}</p>}
          </div>
        </div>
      )}
      {e && (
        <>
          <div className="grid2">
            <div className="panel"><h2>Onde estão os perfis da sua lista</h2>
              <PlotChart options={poolPlot} label="Perfis no mapa do mercado, agregados" />
              <p className="small muted">{e.pool_size} perfis; células com menos pessoas que o limite de anonimato não
                aparecem ({e.pool_map.hidden_cells} ocultas). O losango é a sua vaga.</p></div>
            <div className="panel"><h2>Perfis por cidade</h2>
              <GeoMap points={e.cities.map((c) => ({ lat: c.lat, lon: c.lon, value: c.count, label: `${c.name}: ${c.count}` }))}
                label="Perfis por cidade" />
              {e.cities.length === 0 && <p className="small muted">Nenhuma cidade com perfis suficientes para mostrar.</p>}</div>
          </div>
          <div className="grid2">
            <div className="panel"><h2>Mercado: vagas parecidas</h2>
              <p>Teto salarial das {e.benchmark.n_with_salary} vagas parecidas que informam salário: P25 {money(e.benchmark.p25)},
                mediana {money(e.benchmark.p50)}, P75 {money(e.benchmark.p75)}. A sua: {money(e.benchmark.own_comp_brl_month)}.</p>
              <ul className="small">{e.benchmark.jobs.slice(0, 6).map((b, i) => (
                <li key={i}>{b.title} · similaridade {b.similarity.toFixed(2)} · {money(b.comp_brl_month)}
                  {b.approx_fx ? " (câmbio aproximado)" : ""}</li>))}</ul></div>
            <div className="panel"><h2>Por que candidatos recusaram esta vaga</h2>
              <p className="small">Total de recusas: {e.candidate_reasons.total}</p>
              <ul>{e.candidate_reasons.rows.map((r, i) => <li key={i}>{r.label}: {r.count}</li>)}</ul>
              <p className="small muted">{e.candidate_reasons.note}</p>
              <h3>Concorrência pelos mesmos perfis</h3>
              <p className="small">{e.congestion.text}: <strong>{e.congestion.top5_in_other_lists}</strong></p></div>
          </div>
        </>
      )}
    </section>
  );
}
