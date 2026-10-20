"""The rules page (spec 9.1): one Jinja2 template → docs/RULES.md and the in-app page, both from RULES.

No rule number is written by hand: every number comes from ``RULES`` and the worked example is computed by the
ranking engine itself, so the page and the ranking cannot disagree.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app import texts
from app.config import REPO_ROOT, RULES, Rules, rules_hash
from app.schemas import Offers, Wants

TEMPLATE_DIR = Path(__file__).parent
RULES_MD_PATH = REPO_ROOT / "docs" / "RULES.md"

_QUESTIONS = {
    "atende": "Você atende ao que a vaga pede?",
    "interessa": "A vaga oferece o que você quer?",
    "historico": "Parece com o que você curtiu?",
}


def num(x: float) -> str:
    if float(x).is_integer():
        return str(int(x))
    return f"{x:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def pct(x: float) -> str:
    return f"{num(round(x * 100, 2))}%"


def _criteria(rules: Rules) -> list[dict]:
    measures = {
        "requirements": "ver abaixo (ordem lexicográfica)",
        "semantic": "cosseno entre a vaga e o seu perfil (modelo de embeddings multilíngue)",
        "title": "cosseno entre o título da vaga e a média dos títulos das suas experiências",
        "seniority": "distância na escada de senioridade",
        "salary": "folga = (teto da vaga − seu mínimo) / seu mínimo, com câmbio aproximado",
        "distance": "0 se a vaga é remota (e você aceita) ou na mesma cidade; senão, a distância em km",
        "timezone": f"horas de sobreposição do expediente {rules.workday.start_hour}h–{rules.workday.end_hour}h "
        "(só vagas remotas)",
        "history": "parecença com o que você curtiu e recusou (só no feedback-v1)",
    }
    out = []
    for pillar in rules.criteria.pillars:
        for crit in getattr(rules.criteria, pillar):
            out.append(
                {
                    "pillar_label": texts.PILLAR_LABELS[pillar],
                    "question": _QUESTIONS[pillar],
                    "label": texts.CRITERION_LABELS[crit],
                    "measure": measures[crit],
                    "better": "maior" if rules.criteria.better[crit] == "max" else "menor",
                }
            )
    return out


def _reason_rows(rules: Rules) -> tuple[list[dict], list[dict]]:
    fb = rules.feedback

    def effect(reason: str, lam: float, side: str) -> str:
        if side == "C" and reason == "company":
            return f"só vagas daquela empresa perdem {num(fb.company_penalty)}, com o mesmo decaimento"
        if reason == "none":
            extra = "; só permitido para quem não se candidatou" if side == "B" else ""
            return f"λ = {num(lam)}{extra}"
        if lam > 0:
            return f"feedback semântico negativo, λ = {num(lam)}"
        return "sem penalidade semântica" + ("; vira preferência revelada no Explorar" if side == "C" else "")

    c_rows = [
        {"label": texts.REASON_LABELS_CANDIDATE.get(k, "sem motivo"), "effect": effect(k, v, "C")}
        for k, v in fb.lambda_candidate.items()
    ]
    b_rows = [
        {"label": texts.REASON_LABELS_RECRUITER.get(k, "sem motivo"), "effect": effect(k, v, "B")}
        for k, v in fb.lambda_recruiter.items()
    ]
    b_rows += [
        {"label": texts.REASON_LABELS_RECRUITER[k], "effect": "nenhum efeito (não diz nada sobre o candidato)"}
        for k in fb.ignored_recruiter
    ]
    return c_rows, b_rows


def worked_example(rules: Rules = RULES) -> dict:
    """1 candidate × 3 jobs, ranked by the real engine with ``rules`` (similarities fixed for the example)."""
    from app.ranking.engine import rank
    from app.ranking.explain import raw_text
    from app.ranking.features import CandidateFeatures, JobFeatures
    from app.ranking.service import evaluate_pair

    vec = np.zeros(4, dtype=np.float32)
    wants = Wants(comp_min=5000, arrangements=["remote", "hybrid"], max_distance_km=50)
    cand = CandidateFeatures(
        candidate_id=0,
        revision_id=0,
        proven={"sql", "python"},
        proven_recent={"sql", "python"},
        listed={"power_bi"},
        languages={"pt": 5},
        level=2,
        city_id="florianopolis-sc-br",
        country="BR",
        tz="America/Sao_Paulo",
        wants=wants,
        domains={"analytics", "backend", "ml", "data_eng"},
        emb=vec,
        title_emb=vec,
    )

    def job(
        jid: int, title: str, must: list[str], arrangement: str, city: str | None, comp: tuple | None, level: int
    ) -> JobFeatures:
        offers = Offers(
            arrangement=arrangement,
            comp_min=comp[0] if comp else None,  # type: ignore[arg-type]
            comp_max=comp[1] if comp else None,
            currency="BRL" if comp else None,
            period="month" if comp else None,
        )
        return JobFeatures(
            jid,
            1,
            "market",
            "open",
            "exemplo",
            None,
            None,
            title,
            must,
            [],
            [],
            level,
            arrangement,
            city,
            "BR",
            "America/Sao_Paulo",
            [],
            offers,
            ["analytics"],
            vec,
            vec,
            must,
        )

    jobs = [
        (
            job(1, "Analista de Dados (remota)", ["sql", "python", "power_bi"], "remote", None, (6000, 7000), 2),
            0.71,
            0.80,
        ),
        (
            job(
                2,
                "Cientista de Dados (híbrida)",
                ["python", "machine_learning", "statistics"],
                "hybrid",
                "florianopolis-sc-br",
                None,
                3,
            ),
            0.58,
            0.52,
        ),
        (
            job(3, "Analista de BI (híbrida)", ["sql", "power_bi", "dax"], "hybrid", "sao-jose-sc-br", (4000, 4500), 2),
            0.66,
            0.74,
        ),
    ]
    pairs = [evaluate_pair(cand, j, sem, tit, "candidate", j.job_id) for j, sem, tit in jobs]
    result = rank(pairs, side="candidate", ranker="static-v1", rules=rules)
    titles = {j.job_id: j.title for j, _, _ in jobs}
    rows = []
    for it in sorted(result.items, key=lambda x: x.item_id):
        raw = {c: raw_text(c, it.criteria[c], it.req, "candidate") for c in it.criteria}
        pos = {c: num(it.criteria[c]["position"]) for c in it.criteria}
        a, i = it.pillars["atende"], it.pillars["interessa"]
        rows.append(
            {
                "title": titles[it.item_id],
                "raw": raw,
                "pos": pos,
                "atende": f"{num(a['sum'])} → {num(a['position'])}ª",
                "interessa": f"{num(i['sum'])} → {num(i['position'])}ª",
                "total": num(it.final_sum),
                "order": it.order,
            }
        )
    ordered = sorted(result.items, key=lambda x: x.order)
    first = ordered[0]
    narrative = (
        f'**Resultado:** a vaga "{titles[first.item_id]}" fica em 1º lugar com total '
        f"{num(first.final_sum)} (Atende {num(first.pillars['atende']['position'])}ª + Interessa "
        f"{num(first.pillars['interessa']['position'])}ª). Quem tem a menor soma vem primeiro."
    )
    for a, b in zip(ordered, ordered[1:], strict=False):
        if abs(a.final_sum - b.final_sum) < 1e-9:
            narrative += (
                f' "{titles[a.item_id]}" e "{titles[b.item_id]}" empatam na soma ({num(a.final_sum)}); '
                f'"{titles[a.item_id]}" vem antes porque está melhor em Atende '
                f"({num(a.pillars['atende']['position'])}ª contra {num(b.pillars['atende']['position'])}ª)."
            )
    return {
        "rows": rows,
        "narrative": narrative,
        "wants_text": texts.fmt_money(5000, "BRL"),
        "arrangements_text": "vagas remotas e híbridas até 50 km",
    }


def build_context(rules: Rules = RULES) -> dict:
    reasons_c, reasons_b = _reason_rows(rules)
    sources = rules.ingest.sources
    return {
        "r": rules,
        "w": rules.aggregation.weighted,
        "hash": rules_hash(rules),
        "num": num,
        "pct": pct,
        "ladder": sorted(rules.seniority.ladder.items()),
        "criteria": _criteria(rules),
        "reasons_c": reasons_c,
        "reasons_b": reasons_b,
        "hidden": ", ".join(texts.BLIND_HIDDEN_LABELS[h] for h in rules.privacy.blind_hidden),
        "llm_consent_text": texts.LLM_CONSENT_TEXT,
        "sources_on": ", ".join(s.label for s in sources.values() if s.enabled) or "nenhuma",
        "sources_off": ", ".join(s.label for s in sources.values() if not s.enabled) or "nenhuma",
        "example": worked_example(rules),
    }


def render_markdown(rules: Rules = RULES) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=False,
    )
    return env.get_template("rules.md.j2").render(**build_context(rules))


def render_html(markdown: str) -> str:
    from markdown_it import MarkdownIt

    return MarkdownIt("commonmark", {"html": False}).enable("table").render(markdown)


def export_rules_md(path: Path = RULES_MD_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(), encoding="utf-8", newline="\n")
    return path
