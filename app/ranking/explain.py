"""Explanations (spec 9.2–9.5): every card says why it is there, every filtered job says why it is not.

Positions appear only here, never on the card face, next to the sentence that separates the relative
position from the absolute "bom encaixe" rule. The positions shown reconstruct the deck order exactly.
"""

from __future__ import annotations

from collections import defaultdict

from app import taxonomy as tax_mod
from app import texts
from app.config import RULES
from app.ranking.counterfactual import Counterfactual
from app.ranking.engine import FilteredItem, RankedItem
from app.ranking.pair import RequirementEval

PILLAR_OF = {c: p for p in ("atende", "interessa", "historico") for c in getattr(RULES.criteria, p)}


def _pct(x: float) -> str:
    return f"{x * 100:+.0f}%".replace("+", "+ ").replace("-", "− ")


def requirements_text(req: RequirementEval) -> str:
    if not req.known:
        return "a vaga não tem requisitos obrigatórios identificados (" + texts.UNKNOWN_TEXT + ")"
    parts = [f"{texts.fmt_credit(req.must_credit)} de {req.must_total} obrigatórios comprovados"]
    parts[0] += f" ({texts.fmt_credit(req.recent_credit)} nos últimos {RULES.requirements.recent_years} anos)"
    if req.listed_credit:
        parts.append(f"{texts.fmt_credit(req.listed_credit)} só listado(s), sem experiência com datas")
    if req.nice_total:
        parts.append(f"desejáveis: {texts.fmt_credit(req.nice_credit)} de {req.nice_total}")
    return "; ".join(parts)


def raw_text(crit: str, data: dict, req: RequirementEval, side: str) -> str:
    raw, info = data["raw"], data.get("info", {})
    if data.get("not_applicable"):
        return texts.NOT_APPLICABLE_TEXT + " (vaga não remota)"
    if crit == "requirements":
        return requirements_text(req)
    if raw is None:
        return texts.UNKNOWN_TEXT
    if crit == "semantic":
        return f"similaridade {raw:.2f}".replace(".", ",")
    if crit == "title":
        return f"similaridade de cargo {raw:.2f}".replace(".", ",")
    if crit == "seniority":
        gap = "mesmo nível" if raw == 0 else ("1 nível de distância" if raw == 1 else f"{raw} níveis de distância")
        return (
            f"vaga {texts.seniority_label(info.get('job_level'))}, perfil "
            f"{texts.seniority_label(info.get('candidate_level'))} ({gap})"
        )
    if crit == "salary":
        who = "ao seu mínimo" if side == "candidate" else "ao mínimo do candidato"
        return (
            f"até {texts.fmt_money(info['job_comp'], info.get('currency', 'BRL'), info.get('period', 'month'))} "
            f"({_pct(raw)} em relação {who})"
        )
    if crit == "distance":
        if info.get("remote"):
            return "vaga remota"
        return "mesma cidade" if raw == 0 else f"a {texts.fmt_number(raw)} km"
    if crit == "timezone":
        return (
            f"{texts.fmt_number(raw, 1).rstrip('0').rstrip(',')} h de sobreposição no expediente "
            f"{RULES.workday.start_hour}h–{RULES.workday.end_hour}h"
        )
    if crit == "history":
        return f"{raw:+.2f}".replace(".", ",")
    return str(raw)


def flags_text(item: RankedItem) -> list[str]:
    out = []
    for data in item.criteria.values():
        if "fx" in data.get("flags", []):
            out.append(texts.FX_FLAG)
    sal = item.criteria.get("salary")
    if sal and sal["raw"] is None and sal["info"].get("job_comp") is None:
        out.append(texts.SALARY_UNKNOWN_FLAG)
    return out


def why_summary(req: RequirementEval) -> str:
    """ "Você aparece para esta vaga porque atende 4 de 5 skills obrigatórias e já usou SQL e Python…" """
    tax = tax_mod.load()
    if not req.known:
        return "Esta vaga não lista requisitos obrigatórios que o Encaixe reconheça."
    recent = [tax.label(st.skill) for st in req.must_status if st.status == "proven_recent"][:3]
    sentence = (
        f"Você aparece para esta vaga porque comprova {texts.fmt_credit(req.must_credit)} de "
        f"{req.must_total} requisitos obrigatórios"
    )
    if recent:
        joined = recent[0] if len(recent) == 1 else ", ".join(recent[:-1]) + " e " + recent[-1]
        sentence += f" e já usou {joined} nos últimos {RULES.requirements.recent_years} anos"
    return sentence + "."


def good_fit_text(item: RankedItem) -> str:
    g = item.good_fit
    rule = (
        f"comprovar ≥ {int(RULES.good_fit.must_share * 100)}% dos obrigatórios e estar a no máximo "
        f"{RULES.good_fit.max_seniority_gap} nível de senioridade"
    )
    if not g.evaluable:
        return f"Bom encaixe não pode ser avaliado: a vaga não lista requisitos obrigatórios reconhecidos ({rule})."
    if g.is_good_fit:
        return f"Bom encaixe: {texts.fmt_credit(g.must_credit)} de {g.must_total} obrigatórios ({rule})."
    return f"Ainda não é bom encaixe: {texts.fmt_credit(g.must_credit)} de {g.must_total} obrigatórios ({rule})."


def explain_item(item: RankedItem, n_items: int, side: str) -> dict:
    lines = []
    for crit, data in item.criteria.items():
        lines.append(
            {
                "criterion": crit,
                "label": texts.CRITERION_LABELS[crit],
                "pillar": PILLAR_OF.get(crit),
                "raw_text": raw_text(crit, data, item.req, side),
                "position": data["position"],
                "position_text": f"{texts.ordinal(data['position'])} de {n_items}",
                "unknown": data["unknown"],
                "not_applicable": data["not_applicable"],
            }
        )
    pillars = [
        {
            "pillar": p,
            "label": texts.PILLAR_LABELS[p],
            "sum": v["sum"],
            "position": v["position"],
            "text": (
                f"{texts.PILLAR_LABELS[p]}: soma {texts.fmt_credit(v['sum'])} → "
                f"{texts.ordinal(v['position'])} de {n_items}"
            ),
        }
        for p, v in item.pillars.items()
    ]
    history = [
        {
            "item_id": h.get("item_id"),
            "title": h.get("title"),
            "liked": h.get("liked"),
            "weight": h.get("weight"),
            "text": h.get("text"),
        }
        for h in item.history_top
    ]
    return {
        "lines": lines,
        "pillars": pillars,
        "final_sum": item.final_sum,
        "order": item.order,
        "n_items": n_items,
        "final_text": f"Soma dos pilares: {texts.fmt_credit(round(item.final_sum, 2))} → {texts.ordinal(item.order)} "
        f"de {n_items}",
        "tie_break_text": "Empate na soma: vem antes quem está melhor em Atende, depois em Requisitos.",
        "applicants_first_text": texts.APPLICANTS_FIRST_TEXT if side == "recruiter" else None,
        "history": history,
        "flags": flags_text(item),
        "note": texts.POSITION_NOTE if side == "candidate" else texts.POSITION_NOTE_RECRUITER,
        "good_fit_text": good_fit_text(item),
        "summary": why_summary(item.req),
    }


def requirement_chips(req: RequirementEval) -> dict:
    """Card face: each must/nice with its status (no positions)."""
    tax = tax_mod.load()
    must = [{"skill": st.skill, "label": tax.label(st.skill), "status": st.status} for st in req.must_status]
    for code, rank, met in req.languages:
        level = tax.level_order[rank - 1] if rank else None
        label = texts.LANGUAGE_LABELS.get(code, code) + (f" {texts.LANGUAGE_LEVEL_LABELS[level]}" if level else "")
        must.append({"skill": f"lang:{code}", "label": label, "status": "proven_recent" if met else "missing"})
    nice = [{"skill": st.skill, "label": tax.label(st.skill), "status": st.status} for st in req.nice_status]
    return {"must": must, "nice": nice}


def counterfactual_text(cf: Counterfactual) -> str | None:
    tax = tax_mod.load()
    if cf.kind == "none":
        return None
    if cf.kind == "not_small":
        reasons = {
            "seniority_gap": "a distância de senioridade é grande demais para uma mudança pequena no perfil",
            "not_evaluable": "a vaga não lista requisitos obrigatórios reconhecidos",
            "closed": "a vaga está fechada",
            "country_eligibility": "a elegibilidade de país é definida pela empresa",
            "languages": "a vaga exige um idioma num nível que seu perfil não mostra",
        }
        return "Não há mudança pequena que torne esta vaga um bom encaixe: " + reasons.get(cf.reason or "", "—") + "."
    parts = []
    for p in cf.preferences:
        if p["field"] == "arrangements":
            parts.append(f"aceitar vagas {texts.ARRANGEMENT_LABELS.get(p['add'], p['add'])}s")
        elif p["field"] == "max_distance_km":
            parts.append(f"aceitar até {p['value']} km de distância")
        elif p["field"] == "comp_min":
            parts.append(f"reduzir seu mínimo para {texts.fmt_money(p['value'], 'BRL')}")
    if cf.skills:
        labels = [tax.label(s) for s in cf.skills]
        joined = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " e " + labels[-1]
        parts.append(f"com {joined} usado(s) numa experiência recente")
    after = (
        f", você comprovaria {texts.fmt_credit(cf.must_credit_after or 0)} de {cf.must_total} obrigatórios"
        if cf.skills
        else ""
    )
    return "Se você " + " e ".join(parts) + after + " e esta vaga passaria a ser um bom encaixe."


# --------------------------------------------------------------------------- filtered list


def filtered_groups(filtered: list[FilteredItem], describe) -> dict:  # type: ignore[no-untyped-def]
    """ "Vagas que não te mostramos": grouped by the first failing filter (RULES order)."""
    order = {code: i for i, code in enumerate(RULES.filters.codes)}
    groups: dict[str, list[dict]] = defaultdict(list)
    for f in filtered:
        primary = min(f.reasons, key=lambda r: order.get(r.code, 99))
        groups[primary.code].append(
            {
                **describe(f.item_id),
                "reasons": [
                    {
                        "code": r.code,
                        "title": texts.FILTER_TITLES.get(r.code, r.code),
                        "detail": texts.filter_detail(r.code, **_detail_params(r)),
                    }
                    for r in f.reasons
                ],
            }
        )
    out = []
    for code in RULES.filters.codes:
        if code in groups:
            out.append(
                {
                    "code": code,
                    "title": texts.FILTER_TITLES[code],
                    "count": len(groups[code]),
                    "adjust_hint": texts.FILTER_ADJUST_HINTS[code],
                    "adjust": _adjust_field(code),
                    "items": groups[code],
                }
            )
    total = sum(g["count"] for g in out)
    return {
        "total": total,
        "summary": texts.filtered_summary(total, [(g["code"], g["count"]) for g in out]),
        "groups": out,
    }


def _adjust_field(code: str) -> str | None:
    return {
        "arrangement_not_accepted": "arrangements",
        "beyond_distance": "max_distance_km",
        "salary_below_min": "comp_min",
    }.get(code)


def _detail_params(r) -> dict:  # type: ignore[no-untyped-def]
    p = dict(r.detail)
    if r.code == "salary_below_min":
        cur, per = p.pop("currency", "BRL"), p.pop("period", "month")
        p["job_comp"] = texts.fmt_money(p["job_comp"], cur, per)
        p["candidate_comp"] = texts.fmt_money(p["candidate_comp"], cur, per)
    if r.code == "out_of_area":
        tax = tax_mod.load()
        p["job_domains"] = [tax.domain_info.get(d, {}).get("label_pt", d) for d in p.get("job_domains", [])]
    return p
