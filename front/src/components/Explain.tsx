import type { Explanation } from "../api";

/** "Por que estou vendo isto?" — positions appear only here, never on the card face. */
export function ExplainPanel({ e }: { e: Explanation }) {
  return (
    <section className="explain" aria-label="Por que estou vendo isto?">
      <p><strong>{e.summary}</strong></p>
      {e.slot_text && <p className="notice">{e.slot_text}</p>}
      <table>
        <thead>
          <tr><th>Critério</th><th>Valor</th><th>Posição</th></tr>
        </thead>
        <tbody>
          {e.lines.map((l) => (
            <tr key={l.criterion}>
              <td>{l.label}</td>
              <td>{l.raw_text}</td>
              <td>{l.position_text}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="small">
        {e.pillars.map((p) => <li key={p.pillar}>{p.text}</li>)}
        <li><strong>{e.final_text}</strong></li>
        <li className="muted">{e.tie_break_text}</li>
        {e.applicants_first_text && <li className="muted">{e.applicants_first_text}</li>}
      </ul>
      {e.history.length > 0 && (
        <p className="small">Histórico: {e.history.map((h) => h.text).join("; ")}.</p>
      )}
      {e.flags.length > 0 && <p className="small">Avisos: {e.flags.join(" · ")}</p>}
      <p className="small">{e.good_fit_text}</p>
      <p className="small muted">{e.note}</p>
    </section>
  );
}
