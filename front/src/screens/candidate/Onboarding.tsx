import { useState } from "react";
import { api } from "../../api";
import { ErrorBox } from "../../components/common";
import { type Profile, ProfileEditor, type Provenance } from "../../components/ProfileEditor";
import { useApp } from "../../store";

interface Draft extends Profile {
  provenance: Record<string, Provenance>;
  warnings: string[];
  method: string;
  llm_status: string | null;
  llm_cache_key: string | null;
}

export function Onboarding() {
  const rules = useApp((s) => s.rules)!;
  const setCandidate = useApp((s) => s.setCandidate);
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [llm, setLlm] = useState(false); // unchecked by default (spec 6)
  const [visible, setVisible] = useState(rules.privacy.candidate_default_visible);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const parse = async () => {
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      if (file) form.append("file", file);
      else form.append("text", text);
      form.append("llm_consent", String(llm));
      setDraft(await api.postForm<Draft>("/api/candidates/parse", form));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    try {
      const { provenance: _p, warnings: _w, method: _m, llm_status: _s, llm_cache_key, ...profile } = draft;
      const res = await api.post<{ candidate_id: number }>("/api/candidates", {
        profile, visible_to_recruiters: visible, llm_consent: llm, llm_cache_key,
      });
      setCandidate(res.candidate_id, "xray");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  if (!draft) {
    return (
      <section className="stack" aria-labelledby="onb-title">
        <h1 id="onb-title">Cole seu currículo</h1>
        <p className="muted">O Encaixe lê seu CV, mostra o que entendeu (e de onde tirou cada coisa) e você corrige antes de
          salvar. Depois, o Raio-X mostra onde você está no mercado.</p>
        <textarea aria-label="Texto do currículo" value={text} onChange={(e) => setText(e.target.value)}
          placeholder="Cole aqui o texto do seu CV…" />
        <label className="field">Ou envie um PDF
          <input type="file" accept="application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <label className="toggle"><input type="checkbox" checked={llm} onChange={(e) => setLlm(e.target.checked)} />
          {rules.privacy.texts.llm_consent}</label>
        <label className="toggle"><input type="checkbox" checked={visible} onChange={(e) => setVisible(e.target.checked)} />
          {rules.privacy.texts.visibility_toggle}</label>
        <p className="small muted">{rules.privacy.texts.blind_card}</p>
        <ErrorBox error={error} />
        <div><button type="button" className="btn primary" disabled={busy || (!text.trim() && !file)} onClick={parse}>
          {busy ? "Lendo…" : "Ler meu CV"}</button></div>
      </section>
    );
  }
  return (
    <section className="stack" aria-labelledby="rev-title">
      <h1 id="rev-title">Confira o que entendemos</h1>
      <p className="muted">Cada campo diz se foi <span className="chip stated">declarado</span> no seu texto ou{" "}
        <span className="chip inferred">inferido</span>. Corrija o que precisar.</p>
      {draft.llm_status && <p className="small muted">Leitura por IA: {draft.llm_status}</p>}
      {draft.warnings.map((w) => <p key={w} className="notice small">{w}</p>)}
      <ProfileEditor value={draft} onChange={(p) => setDraft({ ...draft, ...p })} provenance={draft.provenance}
        rules={rules} />
      <ErrorBox error={error} />
      <div className="row">
        <button type="button" className="btn" onClick={() => setDraft(null)}>Voltar</button>
        <button type="button" className="btn primary" disabled={busy} onClick={save}>Salvar e ver meu Raio-X</button>
      </div>
    </section>
  );
}
