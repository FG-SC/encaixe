import * as Plot from "@observablehq/plot";
import { useMemo } from "react";
import { api } from "../../api";
import { ErrorBox, Loading, useAsync } from "../../components/common";
import { PlotChart } from "../../components/PlotChart";
import { useApp } from "../../store";

interface XRayData {
  understood: { headline: string | null; seniority_label: string; city: string | null; proven: string[];
    proven_recent: string[]; listed: string[]; domains: string[]; languages: { language: string }[] };
  good_fit_count: number;
  n_open: number;
  n_eligible: number;
  n_filtered: number;
  top_unlock: { skill: string; label: string; jobs: number }[];
  star: { x: number; y: number; rule: string } | null;
  map: { points: { job_id: number; x: number; y: number; domain: string | null; title: string; good_fit: boolean;
    filtered: boolean }[]; clusters: { id: number; label: string; cx: number; cy: number; n: number }[] };
  good_fit_rule: string;
  share_card: { good_fit_count: number; top_unlock: string[]; signature: string };
}

export function MarketMap({ data, height = 320 }: { data: XRayData; height?: number }) {
  const options = useMemo<Plot.PlotOptions>(() => ({
    height, inset: 12, x: { axis: null }, y: { axis: null }, color: { legend: true, label: "área" },
    marks: [
      Plot.dot(data.map.points, { x: "x", y: "y", fill: "domain", r: (d: { good_fit: boolean }) => (d.good_fit ? 5 : 3),
        fillOpacity: (d: { filtered: boolean }) => (d.filtered ? 0.25 : 0.75), title: "title" }),
      Plot.text(data.map.clusters, { x: "cx", y: "cy", text: "label", fontSize: 10, fill: "#4b5563" }),
      ...(data.star ? [Plot.text([data.star], { x: "x", y: "y", text: () => "★", fontSize: 26, fill: "#F59E0B",
        stroke: "#111827", strokeWidth: 0.6 })] : []),
    ],
  }), [data, height]);
  return <PlotChart options={options} label="Mapa do mercado: cada ponto é uma vaga aberta; a estrela é você" />;
}

export function XRay() {
  const candidateId = useApp((s) => s.candidateId)!;
  const setTab = useApp((s) => s.setCandidateTab);
  const { data, error, loading } = useAsync(() => api.get<XRayData>(`/api/candidates/${candidateId}/xray`),
    [candidateId]);
  if (loading && !data) return <Loading text="Montando seu Raio-X…" />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const u = data.understood;
  return (
    <section className="stack" aria-labelledby="xray-title">
      <h1 id="xray-title">Seu Raio-X</h1>
      <div className="grid2">
        <div className="panel stack">
          <h2>O que entendemos</h2>
          <p><strong>{u.headline ?? "—"}</strong> · {u.seniority_label}{u.city ? ` · ${u.city}` : ""}</p>
          <p className="small">Comprovadas: {u.proven.join(", ") || "nenhuma ainda"}</p>
          {u.listed.length > 0 && <p className="small muted">Só listadas: {u.listed.join(", ")}</p>}
          <p className="small muted">Áreas: {u.domains.join(", ") || "—"}</p>
          <p><span className="big" style={{ fontSize: "2rem", fontWeight: 700 }}>{data.good_fit_count}</span> vagas abertas
            são bom encaixe para você (de {data.n_open}).</p>
          <p className="small muted">{data.good_fit_rule}</p>
          <h3>O que mais destravaria vagas</h3>
          <ol>{data.top_unlock.map((t) => (
            <li key={t.skill}><strong>{t.label}</strong>: +{t.jobs} vaga(s) virariam bom encaixe</li>
          ))}</ol>
          <p className="small muted">Simulando a skill usada numa experiência recente; nada muda no seu perfil.</p>
          <button type="button" className="btn primary" onClick={() => setTab("deck")}>Ver minhas vagas</button>
        </div>
        <div className="panel stack">
          <h2>Você no mapa do mercado</h2>
          <MarketMap data={data} />
          {data.star && <p className="small muted">{data.star.rule}</p>}
        </div>
      </div>
      <h2>Card para compartilhar</h2>
      <div className="share" aria-label="Card de compartilhamento, sem dados pessoais">
        <div>
          <div className="small" style={{ opacity: 0.85 }}>Meu Raio-X no Encaixe</div>
          <div className="big">{data.share_card.good_fit_count}</div>
          <div>vagas abertas em que eu sou bom encaixe</div>
        </div>
        <div className="mini-map" style={{ background: "rgba(255,255,255,0.08)", borderRadius: 14, padding: 6 }}>
          <MarketMap data={data} height={170} />
        </div>
        <div>
          <div className="small" style={{ opacity: 0.85 }}>O que mais destravaria vagas para mim</div>
          <strong>{data.share_card.top_unlock.join(" · ")}</strong>
        </div>
        <div className="sig">{data.share_card.signature}</div>
      </div>
      <p className="small muted">Sem nome, contato nem empresa atual: pronto para print.</p>
    </section>
  );
}
