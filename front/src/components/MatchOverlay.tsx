import { useApp } from "../store";

/** "É um encaixe!" — two pieces snapping together: small, quick and memorable. */
export function MatchOverlay() {
  const match = useApp((s) => s.match);
  const close = useApp((s) => s.showMatch);
  if (!match) return null;
  return (
    <div className="match" role="dialog" aria-modal="true" aria-label={match.title}>
      <div className="pieces" aria-hidden="true">
        <div className="piece left" />
        <div className="piece right" />
      </div>
      <h1 style={{ margin: 0 }}>{match.title}</h1>
      <p>{match.text}</p>
      <button type="button" className="btn" onClick={() => close(null)} autoFocus>Continuar</button>
    </div>
  );
}
