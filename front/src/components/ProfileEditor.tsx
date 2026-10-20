import { useMemo, useState } from "react";
import { api, type RulesPublic } from "../api";
import { useAsync } from "./common";

export interface Experience {
  company: string | null;
  role: string;
  seniority: number | null;
  start: string | null; // YYYY-MM-DD
  end: string | null;
  skills_used: string[];
  responsibilities: string | null;
  outcomes: string[];
}

export interface Profile {
  name: string;
  contact: string | null;
  headline: string | null;
  city_id: string | null;
  experiences: Experience[];
  education: { degree: string | null; field: string | null; institution: string | null; start: string | null;
    end: string | null }[];
  skills_listed: string[];
  languages: { language: string; level: string | null }[];
  wants: { comp_min: number | null; currency: string; period: string; arrangements: string[];
    max_distance_km: number | null; languages: unknown[] };
}

export interface Provenance {
  source_span: string | null;
  stated: boolean;
  confidence: number;
  method: string;
}

interface Skill {
  id: string;
  label: string;
  domain: string;
}

function ProvChip({ p }: { p?: Provenance }) {
  if (!p) return null;
  const text = p.method === "user" ? "editado" : p.stated ? "declarado" : "inferido";
  return (
    <span className={`chip ${p.stated ? "stated" : "inferred"}`} title={p.source_span ?? undefined}>
      {text}{p.method === "llm" ? " · IA" : ""}
    </span>
  );
}

const month = (d: string | null) => (d ? d.slice(0, 7) : "");
const fromMonth = (m: string) => (m ? `${m}-01` : null);

export function ProfileEditor({ value, onChange, provenance, rules }: {
  value: Profile;
  onChange: (p: Profile) => void;
  provenance?: Record<string, Provenance>;
  rules: RulesPublic;
}) {
  const skills = useAsync(() => api.get<Skill[]>("/api/meta/skills"), []);
  const cities = useAsync(() => api.get<{ id: string; name: string; state: string; country: string }[]>(
    "/api/meta/cities"), []);
  const label = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of skills.data ?? []) m.set(s.id, s.label);
    return (id: string) => m.get(id) ?? id;
  }, [skills.data]);
  const byLabel = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of skills.data ?? []) m.set(s.label.toLowerCase(), s.id);
    return m;
  }, [skills.data]);
  const prov = provenance ?? {};
  const set = (patch: Partial<Profile>) => onChange({ ...value, ...patch });
  const setExp = (i: number, patch: Partial<Experience>) =>
    set({ experiences: value.experiences.map((e, k) => (k === i ? { ...e, ...patch } : e)) });

  return (
    <div className="stack">
      <div className="grid2">
        <label className="field">Título profissional <ProvChip p={prov["headline"]} />
          <input type="text" value={value.headline ?? ""} onChange={(e) => set({ headline: e.target.value })} />
        </label>
        <label className="field">Cidade <ProvChip p={prov["city_id"]} />
          <select value={value.city_id ?? ""} onChange={(e) => set({ city_id: e.target.value || null })}>
            <option value="">—</option>
            {(cities.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.name}{c.state ? `, ${c.state}` : ""} ({c.country})</option>
            ))}
          </select>
        </label>
      </div>

      <h3>Experiências</h3>
      <p className="small muted">Uma skill conta como <strong>comprovada</strong> quando foi usada numa experiência
        com datas. Skill só listada nunca supera skill comprovada.</p>
      {value.experiences.map((e, i) => (
        <div key={i} className="panel stack">
          <div className="grid2">
            <label className="field">Cargo <ProvChip p={prov[`experiences.${i}.role`]} />
              <input type="text" value={e.role} onChange={(ev) => setExp(i, { role: ev.target.value })} />
            </label>
            <label className="field">Empresa <ProvChip p={prov[`experiences.${i}.company`]} />
              <input type="text" value={e.company ?? ""} onChange={(ev) => setExp(i, { company: ev.target.value || null })} />
            </label>
            <label className="field">Início <ProvChip p={prov[`experiences.${i}.start`]} />
              <input type="month" value={month(e.start)} onChange={(ev) => setExp(i, { start: fromMonth(ev.target.value) })} />
            </label>
            <label className="field">Fim (vazio = atual)
              <input type="month" value={month(e.end)} onChange={(ev) => setExp(i, { end: fromMonth(ev.target.value) })} />
            </label>
          </div>
          <SkillPicker ids={e.skills_used} label={label} byLabel={byLabel} options={skills.data ?? []}
            onChange={(ids) => setExp(i, { skills_used: ids })} title="Skills usadas nesta experiência" />
          <button type="button" className="btn danger" onClick={() =>
            set({ experiences: value.experiences.filter((_, k) => k !== i) })}>Remover experiência</button>
        </div>
      ))}
      <button type="button" className="btn" onClick={() => set({
        experiences: [{ company: null, role: "", seniority: null, start: null, end: null, skills_used: [],
          responsibilities: null, outcomes: [] }, ...value.experiences],
      })}>+ Adicionar experiência</button>

      {value.education.length > 0 && (
        <>
          <h3>Formação</h3>
          <ul className="small">
            {value.education.map((d, i) => (
              <li key={i}>{[d.degree, d.field, d.institution].filter(Boolean).join(" — ")}
                {d.start ? ` (${d.start.slice(0, 4)}–${d.end ? d.end.slice(0, 4) : "em andamento"})` : ""}</li>
            ))}
          </ul>
        </>
      )}

      <SkillPicker ids={value.skills_listed} label={label} byLabel={byLabel} options={skills.data ?? []}
        onChange={(ids) => set({ skills_listed: ids })} title="Skills listadas (sem experiência com datas)" />

      <h3>Preferências</h3>
      <div className="grid2">
        <label className="field">Salário mínimo (R$/mês)
          <input type="number" min={0} step={100} value={value.wants.comp_min ?? ""}
            onChange={(e) => set({ wants: { ...value.wants, comp_min: e.target.value ? Number(e.target.value) : null } })} />
        </label>
        <label className="field">Distância máxima para presencial/híbrida (km)
          <input type="number" min={0} step={10} value={value.wants.max_distance_km ?? ""}
            onChange={(e) => set({ wants: { ...value.wants,
              max_distance_km: e.target.value ? Number(e.target.value) : null } })} />
        </label>
      </div>
      <fieldset className="row" style={{ border: 0, padding: 0 }}>
        <legend className="small muted">Modalidades que você aceita</legend>
        {rules.arrangements.map((a) => (
          <label key={a.code} className="toggle">
            <input type="checkbox" checked={value.wants.arrangements.includes(a.code)} onChange={(e) => {
              const set2 = new Set(value.wants.arrangements);
              if (e.target.checked) set2.add(a.code); else set2.delete(a.code);
              set({ wants: { ...value.wants, arrangements: [...set2] } });
            }} />
            {a.label}
          </label>
        ))}
      </fieldset>
    </div>
  );
}

function SkillPicker({ ids, onChange, label, byLabel, options, title }: {
  ids: string[];
  onChange: (ids: string[]) => void;
  label: (id: string) => string;
  byLabel: Map<string, string>;
  options: Skill[];
  title: string;
}) {
  const [text, setText] = useState("");
  const add = () => {
    const id = byLabel.get(text.trim().toLowerCase());
    if (id && !ids.includes(id)) onChange([...ids, id]);
    setText("");
  };
  const listId = useMemo(() => `skills-${Math.random().toString(36).slice(2)}`, []);
  return (
    <div className="stack" style={{ gap: 6 }}>
      <span className="small muted">{title}</span>
      <div className="chips">
        {ids.map((id) => (
          <span key={id} className="chip">{label(id)}{" "}
            <button type="button" className="btn ghost small" aria-label={`Remover ${label(id)}`}
              onClick={() => onChange(ids.filter((x) => x !== id))}>×</button>
          </span>
        ))}
      </div>
      <div className="row">
        <input type="text" list={listId} value={text} placeholder="Adicionar skill…" aria-label={`Adicionar a: ${title}`}
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
        <datalist id={listId}>{options.map((o) => <option key={o.id} value={o.label} />)}</datalist>
        <button type="button" className="btn" onClick={add}>Adicionar</button>
      </div>
    </div>
  );
}
