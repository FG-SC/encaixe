// Login by e-mail link (no passwords): ask for the link, then confirm it on /entrar#t=… with a click.
import { type FormEvent, useState } from "react";
import { ApiError, api, type Me } from "../api";
import { useApp } from "../store";

function message(err: unknown): string {
  return err instanceof ApiError ? err.message : String(err);
}

export function Login() {
  const setOverlay = useApp((s) => s.setOverlay);
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setSent((await api.post<{ message: string }>("/api/auth/request", { email })).message);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card stack login" aria-labelledby="login-title">
      <h1 id="login-title">Vagas com regras abertas</h1>
      <p>
        O Encaixe mostra por que cada vaga aparece para você, por que outras ficaram de fora e o que mudaria o
        resultado. Recrutadores veem candidatos sem nome nem contato até o encaixe.
      </p>
      {sent ? (
        <p role="status">{sent}</p>
      ) : (
        <form className="stack" onSubmit={submit}>
          <label className="stack">
            Seu e-mail
            <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <button type="submit" className="btn primary" disabled={busy || !email}>Receber link de acesso</button>
          <p className="small muted">Sem senha: enviamos um link que vale por alguns minutos e só uma vez.</p>
        </form>
      )}
      {error && <p role="alert" className="error">{error}</p>}
      <p className="small">
        <button type="button" className="btn ghost small" onClick={() => setOverlay("rules")}>Como o Encaixe decide</button>
      </p>
    </section>
  );
}

export function ConfirmLogin({ token }: { token: string }) {
  const setMe = useApp((s) => s.setMe);
  const [needsTerms, setNeedsTerms] = useState(false);
  const [accept, setAccept] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const me = await api.post<Me>("/api/auth/verify", { token, accept_terms: accept });
      window.history.replaceState(null, "", "/");
      setMe(me);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setNeedsTerms(true);
      else setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card stack login" aria-labelledby="confirm-title">
      <h1 id="confirm-title">Entrar no Encaixe</h1>
      {needsTerms && (
        <label className="toggle">
          <input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} />
          Li e aceito os termos de uso e a política de privacidade do Encaixe
        </label>
      )}
      <button type="button" className="btn primary" disabled={busy || (needsTerms && !accept)} onClick={confirm}>
        Entrar
      </button>
      {error && (
        <p role="alert" className="error">
          {error} <a href="/">Pedir um novo link</a>
        </p>
      )}
    </section>
  );
}

/** The token of a login link (/entrar#t=…), or null. */
export function loginToken(): string | null {
  if (window.location.pathname !== "/entrar") return null;
  return new URLSearchParams(window.location.hash.slice(1)).get("t");
}
