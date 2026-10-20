"""What a candidate sees when an application does not advance (spec 9.4).

The company's structured reason, the objective gaps computed from the schema (must skills missing, seniority
distance, salary outside the range) and the counterfactual. When the reason does not match the data, say so.
Never the recruiter's name; always "não avançou", never "reprovado".
"""

from __future__ import annotations

from sqlmodel import Session

from app import taxonomy as tax_mod
from app import texts
from app.config import RULES
from app.events.status import ApplicationStatus
from app.jobs import company_name
from app.models import Job
from app.ranking.counterfactual import skills_to_full_proof, with_skills
from app.ranking.features import CandidateFeatures, JobFeatures, job_comp_max_for
from app.ranking.pair import evaluate_requirements, good_fit, hard_filters


def _join(labels: list[str]) -> str:
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " e " + labels[-1]


def rejection_feedback(session: Session, st: ApplicationStatus, c: CandidateFeatures, j: JobFeatures) -> dict:
    tax = tax_mod.load()
    job = session.get(Job, st.job_id)
    company = company_name(session, job.company_id) if job else None
    reason = st.reason
    reason_label = texts.REASON_LABELS_RECRUITER.get(reason or "", reason or "não informado")
    gaps, credit_after, total = skills_to_full_proof(c, j)
    gap_labels = [tax.label(s) for s in gaps]
    seniority_gap = abs(j.level - c.level) if j.level is not None and c.level is not None else None
    job_max, fx = job_comp_max_for(j, c.wants)
    salary_out = bool(c.wants.comp_min and job_max is not None and job_max < c.wants.comp_min)
    lines = [
        f"Sua candidatura para **{j.title}**" + (f" ({company})" if company else "") + " não avançou.",
        f"Motivo indicado pela empresa: **{reason_label}**.",
    ]
    counterfactual = None
    if gap_labels:
        lines.append("O que a vaga pede e seu perfil ainda não mostra: " + _join(gap_labels) + ".")
        after = with_skills(c, gaps)
        r = evaluate_requirements(after, j)
        becomes = good_fit(after, j, r, not hard_filters(after, j, r, "candidate")).is_good_fit
        how = "Com elas" if len(gap_labels) > 1 else "Com ela"
        if len(gap_labels) == 2:
            how = "Com as duas"
        sentence = f"{how}, você comprovaria {texts.fmt_credit(credit_after)} de {total} obrigatórios"
        sentence += " e passaria a ser um bom encaixe para esta vaga." if becomes else "."
        lines.append(sentence)
        counterfactual = {
            "skills": gaps,
            "must_credit_after": credit_after,
            "must_total": total,
            "becomes_good_fit": becomes,
        }
    elif reason == "skills":
        lines.append("A empresa indicou skills, mas esta vaga não lista skills obrigatórias que faltem no seu perfil.")
    if reason == "seniority":
        if seniority_gap:
            lines.append(
                f"A vaga pede {texts.seniority_label(j.level)} e seu perfil está em {texts.seniority_label(c.level)}."
            )
        else:
            lines.append(
                "A empresa indicou senioridade, mas a vaga e seu perfil estão no mesmo nível pela régua do Encaixe."
            )
    if reason == "salary" and not salary_out:
        lines.append(
            "A empresa indicou salário; pelos dados informados, a faixa da vaga não fica abaixo do seu mínimo."
        )
    lines.append("Próximo passo: quando seu perfil mudar de forma relevante, esta vaga volta para o seu deck.")
    return {
        "reason": reason,
        "reason_label": reason_label,
        "gaps": {
            "skills": [{"skill": s, "label": tax.label(s)} for s in gaps],
            "seniority_gap": seniority_gap,
            "salary_below_min": salary_out,
            "salary_fx": fx,
        },
        "counterfactual": counterfactual,
        "message": " ".join(lines),
        "message_lines": lines,
        "good_fit_rule": f"≥ {int(RULES.good_fit.must_share * 100)}% dos obrigatórios e até "
        f"{RULES.good_fit.max_seniority_gap} nível de distância",
    }
